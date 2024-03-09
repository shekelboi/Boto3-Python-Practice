from time import sleep
from botocore.exceptions import ClientError
import boto3
import random


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
client = boto3.client('ec2')

# Create VPC
vpc = ec2.create_vpc(
    CidrBlock='172.32.0.0/16',
    TagSpecifications=get_name_tag('vpc', 'boto3-vpc')
)

# Create and attach IGW to attach to VPC
igw = ec2.create_internet_gateway(
    TagSpecifications=get_name_tag('internet-gateway', 'boto3-internet-gateway')
)
vpc.attach_internet_gateway(InternetGatewayId=igw.id)

# create private subnet
private_subnet = vpc.create_subnet(
    CidrBlock='172.32.0.0/24',
    TagSpecifications=get_name_tag('subnet', 'boto3-private-subnet')
)

# Retrieve availability zones
azs = client.describe_availability_zones()['AvailabilityZones']
available_azs = [az['ZoneName'] for az in azs]

# Randomly select two distinct availability zones
selected_azs = random.sample(available_azs, 2)

# create 2 public subnets
public_subnets = []
for i, az in enumerate(selected_azs):
    public_subnets.append(vpc.create_subnet(
        CidrBlock=f'172.32.{1 + i}.0/24',
        AvailabilityZone=az,
        TagSpecifications=get_name_tag('subnet', f'boto3-public-subnet-{i + 1}')
    ))

# create route table and route for private subnet
private_rt = vpc.create_route_table(
    TagSpecifications=get_name_tag('route-table', 'boto3-private-rt')
)

private_rt.associate_with_subnet(SubnetId=private_subnet.id)

# create route table and route for public subnet
public_rt = vpc.create_route_table(
    TagSpecifications=get_name_tag('route-table', 'boto3-public-rt')
)

public_rt.create_route(
    DestinationCidrBlock='0.0.0.0/0',
    GatewayId=igw.id
)

for public_subnet in public_subnets:
    public_rt.associate_with_subnet(SubnetId=public_subnet.id)

# Create Private Security group
private_sg = ec2.create_security_group(
    Description='Security group for Private EC2',
    GroupName='private-sg',
    VpcId=vpc.id,
    TagSpecifications=get_name_tag('security-group', 'boto3-private-sg')
)

# Rules for Private SG
private_sg.authorize_ingress(
    IpPermissions=[
        {
            'IpProtocol': 'tcp',
            'FromPort': 22,
            'ToPort': 22,
            'IpRanges': [{'CidrIp': '172.32.0.0/16'}]
        }
    ]
)

# Create Public Security Group
public_sg = ec2.create_security_group(
    Description='Security group for Public EC2',
    GroupName='public-sg',
    VpcId=vpc.id,
    TagSpecifications=get_name_tag('security-group', 'boto3-public-sg')
)

# Rules for public SG
public_sg.authorize_ingress(
    IpPermissions=[
        {
            'IpProtocol': 'tcp',
            'FromPort': 22,
            'ToPort': 22,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        },
        {
            'IpProtocol': 'tcp',
            'FromPort': 80,
            'ToPort': 80,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        }
    ]
)

# Initialize the ELBv2 (ALB) client
elbv2 = boto3.client('elbv2')

# Create a Security Group for the ALB
alb_sg = ec2.create_security_group(
    Description='ALB security group',
    GroupName='alb-sg',
    VpcId=vpc.id,
    TagSpecifications=get_name_tag('security-group', 'boto3-alb-sg')
)

# Allow inbound HTTP traffic to the ALB Security Group
alb_sg.authorize_ingress(
    IpPermissions=[
        {
            'IpProtocol': 'tcp',
            'FromPort': 80,
            'ToPort': 80,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        }
    ]
)

# Create an Application Load Balancer
alb_response = elbv2.create_load_balancer(
    Name='boto3-application-load-balancer',
    Subnets=[subnet.id for subnet in public_subnets],
    SecurityGroups=[alb_sg.id],
    Scheme='internet-facing',
    Tags=[{'Key': 'Name', 'Value': 'boto3-application-load-balancer'}],
    Type='application',
    IpAddressType='ipv4'
)

alb_arn = alb_response['LoadBalancers'][0]['LoadBalancerArn']

# Create a Target Group
target_group_response = elbv2.create_target_group(
    Name='boto3-target-group',
    Protocol='HTTP',
    Port=80,
    VpcId=vpc.id,
    TargetType='instance',
    Tags=[
        {
            'Key': 'Name',
            'Value': 'boto3-target-group'
        }
    ]
)

target_group_arn = target_group_response['TargetGroups'][0]['TargetGroupArn']

# Create a Listener for the ALB that forwards requests to the Target Group
listener_response = elbv2.create_listener(
    LoadBalancerArn=alb_arn,
    Protocol='HTTP',
    Port=80,
    DefaultActions=[
        {
            'Type': 'forward',
            'TargetGroupArn': target_group_arn
        }
    ]
)

listener_arn = listener_response['Listeners'][0]['ListenerArn']

# Retrieve AMI dynamically
client = boto3.client('ec2')
ami_filters = [
    {
        'Name': 'name',
        'Values': [
            'Amazon Linux 2023 AMI 2023.0.20230315.0 x86_64 HVM kernel-6.1 SSD Volume Type by Venv'
        ]
    },
    {
        'Name': 'architecture',
        'Values': [
            'x86_64'
        ]
    }
]
amis = client.describe_images(Filters=ami_filters)
selected_ami = amis['Images'][0]['ImageId']

# Create EC2 for public subnets
public_instances = []
for i, public_subnet in enumerate(public_subnets):
    instance = ec2.create_instances(
        ImageId=selected_ami,
        InstanceType='t2.micro',
        MaxCount=1,
        MinCount=1,
        SubnetId=public_subnet.id,
        SecurityGroupIds=[public_sg.id],
        TagSpecifications=get_name_tag('instance', f'boto3-public-instance-{i + 1}')
    )[0]  # ec2.create_instances() returns a list of instances, we take the first one
    public_instances.append(instance)

# Create EC2 for private subnet
private_instances = []
for i in range(2):
    instance = ec2.create_instances(
        ImageId=selected_ami,
        InstanceType='t2.micro',
        MaxCount=1,
        MinCount=1,
        SubnetId=private_subnet.id,
        SecurityGroupIds=[private_sg.id],
        TagSpecifications=get_name_tag('instance', f'boto3-private-instance-{i + 1}')
    )[0]
    private_instances.append(instance)

# Delete the built infrastructure
input('Press Enter to destroy the infrastructure')

for instance in public_instances:
    instance.terminate()

for instance in private_instances:
    instance.terminate()

for instance in public_instances:
    instance.wait_until_terminated()

for instance in private_instances:
    instance.wait_until_terminated()

private_sg.delete()
public_sg.delete()
elbv2.delete_listener(ListenerArn=listener_arn)
elbv2.delete_target_group(TargetGroupArn=target_group_arn)
elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
elbv2.get_waiter('load_balancers_deleted').wait(LoadBalancerArns=[alb_arn])

while True:
    try:
        alb_sg.delete()
        break
    except ClientError:
        print(f'Waiting for the dependencies of {alb_sg} to be cleaned up.')
        sleep(5)

for subnet in public_subnets:
    subnet.delete()
private_subnet.delete()
public_rt.delete()
private_rt.delete()
vpc.detach_internet_gateway(InternetGatewayId=igw.id)
igw.delete()
vpc.delete()
