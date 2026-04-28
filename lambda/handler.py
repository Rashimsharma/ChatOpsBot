import os
import json
import boto3
from datetime import datetime, timezone

# --- Config via environment variables ---
REGIONS = os.getenv("REGIONS", "us-east-1").split(",")
EBS_COST_PER_GB = float(os.getenv("EBS_COST_PER_GB", "0.10"))
EIP_MONTHLY_COST = float(os.getenv("EIP_MONTHLY_COST", "3.60"))
MIN_VOLUME_AGE_DAYS = int(os.getenv("MIN_VOLUME_AGE_DAYS", "0"))  # optional filter


def lambda_handler(event, context):
    results = []
    total_cost = 0.0

    for region in REGIONS:
        region = region.strip()
        ec2 = boto3.client("ec2", region_name=region)

        # --- Scan EBS Volumes ---
        ebs_data = find_unattached_volumes(ec2, region)
        results.extend(ebs_data["resources"])
        total_cost += ebs_data["cost"]

        # --- Scan Elastic IPs ---
        eip_data = find_unused_eips(ec2, region)
        results.extend(eip_data["resources"])
        total_cost += eip_data["cost"]

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "regions_scanned": REGIONS,
        "total_resources": len(results),
        "estimated_monthly_cost_usd": round(total_cost, 2),
    }

    response = {
        "summary": summary,
        "resources": results,
    }

    print(json.dumps(response, indent=2))  # CloudWatch Logs
    return response


# ---------------------------
# EBS LOGIC
# ---------------------------
def find_unattached_volumes(ec2, region):
    resources = []
    total_cost = 0.0

    paginator = ec2.get_paginator("describe_volumes")
    pages = paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    )

    for page in pages:
        for vol in page["Volumes"]:
            if not is_old_enough(vol):
                continue

            size_gb = vol["Size"]
            cost = size_gb * EBS_COST_PER_GB
            total_cost += cost

            resources.append({
                "resource_type": "EBS",
                "resource_id": vol["VolumeId"],
                "region": region,
                "size_gb": size_gb,
                "volume_type": vol["VolumeType"],
                "state": vol["State"],
                "create_time": vol["CreateTime"].isoformat(),
                "monthly_cost_usd": round(cost, 2),
                "tags": format_tags(vol.get("Tags", []))
            })

    return {"resources": resources, "cost": total_cost}


def is_old_enough(volume):
    if MIN_VOLUME_AGE_DAYS <= 0:
        return True

    create_time = volume["CreateTime"]
    age_days = (datetime.now(timezone.utc) - create_time).days
    return age_days >= MIN_VOLUME_AGE_DAYS


# ---------------------------
# EIP LOGIC
# ---------------------------
def find_unused_eips(ec2, region):
    resources = []
    total_cost = 0.0

    response = ec2.describe_addresses()

    for addr in response["Addresses"]:
        if "AssociationId" in addr:
            continue  # skip attached EIPs

        cost = EIP_MONTHLY_COST
        total_cost += cost

        resources.append({
            "resource_type": "EIP",
            "resource_id": addr.get("AllocationId", "N/A"),
            "public_ip": addr.get("PublicIp"),
            "region": region,
            "monthly_cost_usd": round(cost, 2),
            "tags": format_tags(addr.get("Tags", []))
        })

    return {"resources": resources, "cost": total_cost}


# ---------------------------
# HELPERS
# ---------------------------
def format_tags(tag_list):
    return {tag["Key"]: tag["Value"] for tag in tag_list} if tag_list else {}
