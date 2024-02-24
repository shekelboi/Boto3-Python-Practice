import boto3


def get_name_tag(resource_type, name):
    return [{
        'ResourceType': resource_type,
        'Tags': [
            {
                'Key': 'Name',
                'Value': name,
            },
        ]
    }]


ec2 = boto3.resource('ec2')
vpc = ec2.create_vpc(
    CidrBlock='172.32.0.0/16',
    TagSpecifications=get_name_tag('vpc', 'boto3-vpc')
)

input('Press Enter to destroy the infrastructure')

vpc.delete()
