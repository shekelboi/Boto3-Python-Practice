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

# create 2 public subnets
public_subnets = []
for i in range(2):
    public_subnets.append(vpc.create_subnet(
        CidrBlock=f'172.32.{1 + i}.0/24',
        TagSpecifications=get_name_tag('subnet', f'boto3-public-subnet-{i + 1}')
    ))

# create route table and route for private subnet
private_rt = vpc.create_route_table(
    TagSpecifications=get_name_tag('route-table', 'boto3-private-rt')
)

private_rt.create_route(
    DestinationCidrBlock='0.0.0.0/0',
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

# Deleting the built infrastructure
input('Press Enter to destroy the infrastructure')

for subnet in public_subnets:
    subnet.delete()
private_subnet.delete()
public_rt.delete()
private_rt.delete()
vpc.detach_internet_gateway(InternetGatewayId=igw.id)
igw.delete()
vpc.delete()
