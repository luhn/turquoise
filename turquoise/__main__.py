import sys
from time import time as unix_timestamp, sleep
import re
import boto3


def find_asg(client, name):
    """
    Find an ASG with a name that matches exactly with the name or
    "[name]-[timestamp]".  In case of multiple matches, the later timestamp
    will be taken.

    """
    describe = client.describe_auto_scaling_groups()
    matches = []
    for row in describe['AutoScalingGroups']:
        _name = row['AutoScalingGroupName']
        if _name == name:
            matches.append((0, row))
        else:
            match = re.match(re.escape(name) + r'\-([0-9]+)', _name)
            if match:
                ts = match.group(1)
                matches.append((ts, row))
    if len(matches) == 0:
        return None
    else:
        return sorted(matches, key=lambda x: x[0])[-1][1]


def clone_lc(client, lc, name, image_id):
    """
    Create a new Launch Configuration identical to the one passed in, except
    for the new name and new image ID.

    """
    PARAMS_TO_CLONE = [
        'KeyName',
        'SecurityGroups',
        'ClassicLinkVPCId',
        'ClassicLinkVPCSecurityGroups',
        'UserData',
        'InstanceType',
        'BlockDeviceMappings',
        'InstanceMonitoring',
        'SpotPrice',
        'IamInstanceProfile',
        'EbsOptimized',
        'AssociatePublicIpAddress',
        'PlacementTenancy',
    ]
    try:
        params = {
            key: lc[key] for key in PARAMS_TO_CLONE if key in lc
        }
    except KeyError:
        print(list(lc.keys()))
        raise
    # We need special handling for kernel ID and ramdisk ID.
    if lc['KernelId']:
        params['KernelId'] = lc['KernelId']
    if lc['RamdiskId']:
        params['RamdiskId'] = lc['RamdiskId']
    client.create_launch_configuration(
        LaunchConfigurationName=name,
        ImageId=image_id,
        **params
    )
    return asg_client.describe_launch_configurations(
        LaunchConfigurationNames=[name],
    )['LaunchConfigurations'][0]


def clone_asg(client, asg, name, lc_name):
    """
    Create a new ASG identical to the given one except in name and launch
    configuration.

    """
    PARAMS_TO_CLONE = [
        'MinSize',
        'MaxSize',
        'DesiredCapacity',
        'DefaultCooldown',
        'AvailabilityZones',
        'LoadBalancerNames',
        'HealthCheckType',
        'HealthCheckGracePeriod',
        'PlacementGroup',
        'VPCZoneIdentifier',
        'TerminationPolicies',
        'NewInstancesProtectedFromScaleIn',
    ]
    params = {
        key: asg[key] for key in PARAMS_TO_CLONE if key in asg
    }
    params['Tags'] = [{
        'ResourceId': name,
        'ResourceType': 'auto-scaling-group',
        'Key': tag['Key'],
        'Value': tag['Value'],
        'PropagateAtLaunch': tag['PropagateAtLaunch'],
    } for tag in asg['Tags']]

    client.create_auto_scaling_group(
        AutoScalingGroupName=name,
        LaunchConfigurationName=lc_name,
        **params
    )
    return client.describe_auto_scaling_groups(
        AutoScalingGroupNames=[name]
    )['AutoScalingGroups'][0]


def delete_asg(client, asg):
    """
    Scale down and then delete the ASG.

    """
    asg_client.update_auto_scaling_group(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
        MinSize=0,
        MaxSize=0,
        DesiredCapacity=0,
    )
    asg_client.resume_processes(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
    )

    # Poll for finished terminating.
    for i in range(61):
        if i == 60:
            raise Exception('Polled 60 times, giving up.')
        sleep(10)
        _asg = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg['AutoScalingGroupName']],
        )['AutoScalingGroups'][0]
        # Check instance states
        has_instances = False
        for instance in _asg['Instances']:
            if instance['LifecycleState'] != 'Terminated':
                has_instances = True
                break
        if not has_instances:
            break

    asg_client.delete_auto_scaling_group(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
    )


if __name__ == '__main__':
    asg_client = boto3.client('autoscaling')
    asg_name_base = sys.argv[1]
    asg_new_name = asg_name_base + '-' + str(int(unix_timestamp()))

    print('Searching for ASG...')
    asg = find_asg(asg_client, asg_name_base)
    if asg is None:
        raise Exception('Could not find ASG.')

    print('Loading LC...')
    lc = asg_client.describe_launch_configurations(
        LaunchConfigurationNames=[asg['LaunchConfigurationName']],
    )['LaunchConfigurations'][0]

    print('Suspending ASG...')
    asg_client.suspend_processes(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
    )

    print('Creating new launch configuration...')
    new_lc = clone_lc(asg_client, lc, asg_new_name, sys.argv[2])
    print('Creating new ASG...')
    new_asg = clone_asg(
        asg_client,
        asg,
        asg_new_name,
        new_lc['LaunchConfigurationName'],
    )

    # TODO:  Attach new ASG, wait for health checks, detach old ASG.

    print('Scaling down and deleting old ASG...')
    delete_asg(asg_client, asg)
    print('Deleting old LC...')
    asg_client.delete_launch_configuration(
        LaunchConfigurationName=asg['LaunchConfigurationName'],
    )
