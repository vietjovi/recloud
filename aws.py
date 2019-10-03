import re, os, sys, argparse
import boto3
from pprint import pprint
import requests
import random
import time
from multiprocessing import Process
import csv
import tldextract

from botocore.config import Config

config = Config(
    retries = dict(
        max_attempts = 10
    )
)

domains = []
blacklist = ['amazonaws.com', 'dynu.com', 'bona.com', 'splunkcloud.com', 'elasticbeanstalk.com', 'openvpn.net', 'cisco.com']

with open('ip_list') as f:
    ip_list = [line.strip() for line in f.readlines()]

with open('top-1m.csv') as csvfile:
    reader = csv.DictReader(csvfile)
    for i, row in enumerate(reader):
        if i > 50_000:
            break
        d = row['domain']
        if d not in blacklist:
            domains.append(d)

print(len(domains))
Description = """                      
 _____ _           _ _____                     
|     | |___ _ _ _| | __  |___ ___ ___ ___ ___ 
|   --| | . | | | . |    -| .'|  _| . | . |   |
|_____|_|___|___|___|__|__|__,|___|___|___|_|_|
    Cloud IP Hunting - Proof of Concept [AWS]         
"""

TLDWhitelist = ['.com', '.net', '.org', '.edu', '.co', '.ru', '.app', '.ai']
AWSRegions = ['us-east-2','us-east-1','us-west-1','us-west-2','ca-central-1','eu-central-1','eu-west-1','eu-west-2','eu-west-3','eu-north-1']

Session = None
CSRFToken = None

def get_hostnames(address):
    global Session
    global CSRFToken

    if not Session:
        #print('[+] Opening session for Security Trails ...')

        Session = requests.Session()
        response = Session.get('https://securitytrails.com/list/ip/1.1.1.1')
        CSRFToken = re.findall(r'csrf_token = "(\S+?)"', response.text)[0]

    response = Session.post(f'https://securitytrails.com/app/api/v1/list?ipv4={address}', json = {'_csrf_token' : CSRFToken})

    if response.status_code != 200:
        print('[!] SecurityTrails request failed!')
        print(response.text)
        sys.exit(1)

    records = response.json().pop('records', [])

    if records:
        return [r['hostname'] for r in records]

    return []

def list_current_addresses(args):
    if args.region == 'all':
        regions = AWSRegions
    else:
        regions = [args.region]

    for region in regions:

        engine = boto3.client(
        'ec2',
        aws_access_key_id = args.access_key,
        aws_secret_access_key = args.secret_key,
        region_name = region,
        config=config
        )

        current_addresses = [a['PublicIp'] for a in engine.describe_addresses().pop('Addresses', [])]

        if len(current_addresses) > 1:
            print('\n[+] {} has {}\n'.format(region, len(current_addresses)))

            for addr in current_addresses:
                hostnames = get_hostnames(addr)
                print('{:15} : {}'.format(addr, '|'.join(hostnames)))

    print('')

def main(arguments):

    parser = argparse.ArgumentParser(description=Description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('region', choices=AWSRegions + ['all'], help="AWS Region to search")
    parser.add_argument('-c', '--count', type=int, help="Number of IPs to try", default = 10000)
    parser.add_argument('-l', '--list', help="List current IP info", action="store_true")
    parser.add_argument('-aK', '--access-key', help="AWS access key")
    parser.add_argument('-sK', '--secret-key', help="AWS secret key")
    args = parser.parse_args(arguments)

    print(Description)

    if args.list:
        return list_current_addresses(args)

    if args.region == 'all':
        print("[!] 'All' is not valid when hunting")
        return

    engine = boto3.client(
    'ec2',
    aws_access_key_id = args.access_key,
    aws_secret_access_key = args.secret_key,
    region_name = args.region,
    config=config
    )

    print('\n[+] Connected to AWS. Hunting in {} ... (max: {})\n'.format(args.region, args.count))

    for l in range(0, args.count):
        
        for _ in range(3):
            try:
                eip = engine.allocate_address(Domain='vpc')
                break
            except Exception:
                time.sleep(1)
                print('Allocate exception')
        
        address = eip['PublicIp']
        allocation_id = eip['AllocationId']

        if address in ip_list:
            print('Hooray, the ip in the list: {}'.format(address))
            break

        try:
            hostnames = get_hostnames(address)
        except Exception:
            print('Issues with trails')
            time.sleep(0.2)
            hostnames = []
        if hostnames:
            valid_tld = any(True if '.'.join(tldextract.extract(hostname)[1:]) in domains else False for hostname in hostnames)

            if not valid_tld:
                print('\t= {} : {}'.format(address, hostnames[0]))
                time.sleep(0.1)
            else:
                print('\t+++ {} : {}'.format(address, '|'.join(hostnames)))
                break

        print('\t- {:15}'.format(address), end = '\r')
        for _ in range(3):
            try:
                engine.release_address(AllocationId=allocation_id)
                break
            except Exception:
                time.sleep(1)
                print('Realese exception')


    print('\n')


if __name__ == '__main__':
    procs = []
    for _ in range(5):
        proc = Process(target=main, args=(sys.argv[1:],))
        procs.append(proc)
        proc.start()
        time.sleep(1)

    for proc in procs:
        proc.join()