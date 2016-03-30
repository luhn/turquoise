Turquoise
=========

.. warning::

   Turquoise is still in development and will see major changes as it evolves.

Turquoise is a CLI utility for performing blue-green deploys on AWS Auto
Scaling Groups.  When invoked, it will create a new auto scaling group with the
specified AMI, wait until all instances have booted and are passing health
checks (including ELB health checks if applicable), and the delete the old auto
scaling group.

Although Amazon CloudFormation has a rolling update feature for auto scaling
groups, it does not take into account ELB health checks, which can cause
periods where no instances registered in the load balancer are healthy, leading
to downtime.

Usage
-----

You'll need two things to use Turquoise:  a base name and an AMI.

The base name is an string of your choosing. Turquoise will use the base name
to construct a name for the new auto scaling group.  The new name is the base
name plus a hyphen plus the current unix timestamp.  For example, if your base
name is ``my-asg``, a new auto scaling name might be ``my-asg-1459314750``.

The base name will also be used to find the current auto scaling group.
Turquoise will search for auto scaling groups that a name equal to the base
name or a valid name constructed from the base name.  If multiple auto scaling
groups are found, the one with the latest timestamp will be used.

To obtain an AMI ID, we recommend using Packer_ to
automate building an AMI.  However, any valid AMI will work.

With those in hand, using Turquoise is easy::

    turquoise [base name] [ami id]

Turquoise uses boto_, so you can
authenticate yourself with AWS using the `credentials file`_ or
`environment variables`_.

Give it a few minutes to finish running and you'll have a new auto scaling
group running instances with your new AMI.

.. _Packer: https://www.packer.io/
.. _boto: https://boto3.readthedocs.org/en/latest/
.. _`credentials file`: http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html#cli-config-files
.. _`environment variables`: http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html#cli-environment
