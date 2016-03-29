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
    return client.describe_launch_configurations(
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


def wait_for_instances(client, asg, desired_state=None, desired_health=None,
                       desired_count=None):
    """
    Poll until all the instances in the ASG match the desired state and health.

    """
    for i in range(61):
        if i == 60:
            raise Exception('Tried for 5 minutes, giving up.')
        sleep(10)
        _asg = client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg['AutoScalingGroupName']],
        )['AutoScalingGroups'][0]

        if(
                desired_count is not None and
                len(_asg['Instances']) < desired_count
        ):
            continue

        # Check instance states
        all_matching = True
        for instance in _asg['Instances']:
            print(instance['LifecycleState'], instance['HealthStatus'])
            if(
                    desired_state is not None and
                    instance['LifecycleState'] != desired_state
            ):
                all_matching = False
                break
            if(
                    desired_health is not None and
                    instance['HealthStatus'] != desired_health
            ):
                all_matching = False
                break
        if all_matching:
            break


def wait_for_lb_instances(client, lb_name):
    for i in range(61):
        if i == 60:
            raise Exception('Tried for 5 minutes, giving up.')

        if i != 0:
            sleep(10)

        response = client.describe_instance_health(
            LoadBalancerName=lb_name,
        )
        all_healthy = True
        for instance in response['InstanceStates']:
            if instance['State'] != 'InService':
                all_healthy = False
                break
        if all_healthy:
            break


def delete_asg(client, asg):
    """
    Scale down and then delete the ASG.

    """
    if len(asg['LoadBalancerNames']) > 0:
        client.detach_load_balancers(
            AutoScalingGroupName=asg['AutoScalingGroupName'],
            LoadBalancerNames=asg['LoadBalancerNames'],
        )
    client.update_auto_scaling_group(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
        MinSize=0,
        MaxSize=0,
        DesiredCapacity=0,
    )
    client.resume_processes(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
    )

    wait_for_instances(client, asg, 'Terminated')

    client.delete_auto_scaling_group(
        AutoScalingGroupName=asg['AutoScalingGroupName'],
    )


if __name__ == '__main__':
    asg_client = boto3.client('autoscaling')
    elb_client = boto3.client('elb')
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

    has_lbs = len(asg['LoadBalancerNames']) > 0
    if has_lbs:
        asg_client.attach_load_balancers(
            AutoScalingGroupName=asg_new_name,
            LoadBalancerNames=asg['LoadBalancerNames'],
        )

    print('Waiting for instances to boot...')
    wait_for_instances(
        asg_client, new_asg, 'InService', 'Healthy',
        new_asg['DesiredCapacity'],
    )

    if has_lbs:
        # Wait for LB health checks
        print('Waiting for ELB health checks...')
        for lb_name in asg['LoadBalancerNames']:
            wait_for_lb_instances(elb_client, lb_name)

    print('Scaling down and deleting old ASG...')
    delete_asg(asg_client, asg)
    print('Deleting old LC...')
    asg_client.delete_launch_configuration(
        LaunchConfigurationName=asg['LaunchConfigurationName'],
    )
