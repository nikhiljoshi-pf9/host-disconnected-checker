#!/usr/bin/env python3
"""
test3 (final) - PMK / PMO (unchanged) + FIXED PCD flow.

PCD flow:
 - ask region (default us-west-2)
 - saml2aws login (interactive)
 - aws eks update-kubeconfig (hard-coded per region)
 - ask namespace
 - run consul-dump-yaml inside resmgr pod to get dbserverid (uses pod's $CUSTOMER_ID/$REGION_ID)
 - run consul-dump-yaml for the dbserver to get admin_pass (stored in ADMIN_PASS; not printed)
 - ask for host_id
 - run mysql query inside mysqld-exporter using admin_pass
"""
import subprocess
import shlex
import re
import os
import sys

def run_shell(cmd, capture=False, interactive=False):
    """Run a shell command (string). If capture=True return stdout (str).
       If interactive=True, run without capturing so interactive prompts/MFA work.
       Returns stdout string (if capture) or None.
       On failure prints helpful info and returns None.
    """
    print(f"\n👉 Running: {cmd}")
    try:
        if interactive:
            subprocess.run(cmd, shell=True, check=True)
            return None
        if capture:
            res = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            return res.stdout
        else:
            subprocess.run(cmd, shell=True, check=True)
            return None
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")
        if hasattr(e, "stdout") and e.stdout:
            print("STDOUT:\n", e.stdout)
        if hasattr(e, "stderr") and e.stderr:
            print("STDERR:\n", e.stderr)
        return None

def run_list(cmd_list, capture=False):
    """Run a command given as a list (no shell)."""
    print(f"\n👉 Running: {' '.join(cmd_list)}")
    try:
        if capture:
            res = subprocess.run(cmd_list, check=True, capture_output=True, text=True)
            return res.stdout
        else:
            subprocess.run(cmd_list, check=True)
            return None
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")
        if e.stdout:
            print("STDOUT:\n", e.stdout)
        if e.stderr:
            print("STDERR:\n", e.stderr)
        return None

# -----------------------
# PMK (left as-is)
# -----------------------
def handle_pmk():
    ns = input("Enter namespace: ").strip()
    host_id = input("Enter host ID: ").strip()

    # find mysqld-exporter pod (first match)
    pod_cmd = f"kubectl -n {ns} get pods -o name | grep mysqld-exporter | head -n1"
    pod = subprocess.getoutput(pod_cmd).strip()
    pod = pod.replace("pod/", "")
    if not pod:
        print(f"❌ No mysqld-exporter pod found in namespace {ns}")
        return

    print(f"✅ Using pod: {pod}")

    query = f"SELECT id,hostname,responding FROM hosts WHERE id='{host_id}';"
    mysql_cmd = [
        "kubectl", "exec", "-n", ns, "deploy/mysqld-exporter", "-c", "mysqld-exporter",
        "--", "mysql", "resmgr", "-e", query
    ]
    out = run_list(mysql_cmd, capture=True)
    if out is None:
        print("❌ MySQL query failed.")
        return
    print("\n✅ Query result:")
    # pretty-print table
    lines = [line for line in out.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        print("(no rows)")
        return
    headers = lines[0].split()
    rows = [line.split() for line in lines[1:]]
    # Calculate column widths
    col_widths = [max(len(str(item)) for item in [header] + [row[i] for row in rows]) for i, header in enumerate(headers)]
    def format_row(row):
        return " | ".join(str(item).ljust(col_widths[i]) for i, item in enumerate(row))
    # Print header
    print(format_row(headers))
    print("-+-".join('-' * w for w in col_widths))
    # Print rows
    for row in rows:
        print(format_row(row))

# -----------------------
# PMO (left as-is)
# -----------------------
def handle_pmo():
    fqdn = input("Enter FQDN: ").strip()
    host_id = input("Enter host ID: ").strip()

    # run remote command via ssh (uses sudo su - to load root env and source admin_admin.rc)
    remote = (
        "sudo su - -c '"
        "source admin_admin.rc 2>/dev/null || true; "
        "/opt/pf9/du-tools/du-ctl/du_ctl --format table host list | grep -F \"{host}\"'"
    ).format(host=host_id)
    ssh_cmd = f"ssh -tt -o StrictHostKeyChecking=accept-new nikhil.joshi@{fqdn} {shlex.quote(remote)}"

    # interactive SSH so user can complete any password/MFA
    run_shell(ssh_cmd, interactive=True)

# -----------------------
# PCD (FIXED)
# -----------------------
def handle_pcd():
    # region (default us-west-2)
    region = input("Enter region (us-west-2/eu-central-1) [default: us-west-2]: ").strip() or "us-west-2"
    if region not in ("us-west-2", "eu-central-1"):
        print("❌ Invalid region")
        return

    # 1) saml2aws login (interactive; may prompt MFA)
    saml_cmd = f"saml2aws login --region {region} --role=arn:aws:iam::156041444395:role/PF9-ReadOnly --profile ops-cogs-pcd-prod-readonly"
    print("Note: saml2aws will prompt for your IdP/MFA. Complete that in this terminal.")
    run_shell(saml_cmd, interactive=True)

    # 2) update kubeconfig (hard-coded per your request)
    if region == "us-west-2":
        eks_cmd = "aws eks update-kubeconfig --region us-west-2 --name app-dataplane-1 --profile ops-cogs-pcd-prod-readonly"
    else:  # eu-central-1
        eks_cmd = "aws eks update-kubeconfig --region eu-central-1 --name app-dataplane-1 --profile ops-cogs-pcd-prod-readonly"

    run_shell(eks_cmd, interactive=False)

    # 3) ask for namespace (PCD-specific)
    ns = input("Enter namespace: ").strip()
    if not ns:
        print("❌ Namespace required")
        return

    # 4) run consul-dump-yaml inside resmgr to fetch dbserverid
    # Use bash -lc so that pod's environment variables ($CUSTOMER_ID/$REGION_ID) are evaluated
    cmd1 = (
        f"kubectl exec deploy/resmgr -c resmgr -n {ns} -- "
        f"bash -lc 'consul-dump-yaml --start-key \"customers/$CUSTOMER_ID/regions/$REGION_ID/db\"'"
    )
    db_dump = run_shell(cmd1, capture=True)
    if not db_dump:
        print("⚠ consul-dump-yaml (db list) returned nothing or failed.")
        print("Falling back to interactive shell inside resmgr pod for manual inspection.")
        print("Inside the pod, run:\n  consul-dump-yaml --start-key customers/$CUSTOMER_ID/regions/$REGION_ID/db")
        print("Copy the dbserver id and paste it when prompted.")
        # open interactive shell for manual inspection
        run_shell(f"kubectl exec -it deploy/resmgr -c resmgr -n {ns} -- bash", interactive=True)
        dbserver_id = input("Enter dbserver id (copied from inside pod): ").strip()
        if not dbserver_id:
            print("❌ No dbserver id provided. Aborting.")
            return
    else:
        # parse dbserver id, e.g. line: "dbserver: 58df5f90-..."
        m = re.search(r"dbserver:\s*([a-f0-9-]+)", db_dump, re.IGNORECASE)
        if not m:
            print("⚠ Could not parse dbserver id from consul output. Showing output:")
            print(db_dump)
            print("Falling back to interactive shell for manual inspection.")
            run_shell(f"kubectl exec -it deploy/resmgr -c resmgr -n {ns} -- bash", interactive=True)
            dbserver_id = input("Enter dbserver id (copied from inside pod): ").strip()
            if not dbserver_id:
                print("❌ No dbserver id provided. Aborting.")
                return
        else:
            dbserver_id = m.group(1)
            print(f"✅ Found dbserver id: {dbserver_id}")

    # 5) fetch dbserver details to grab admin_pass
    cmd2 = (
        f"kubectl exec deploy/resmgr -c resmgr -n {ns} -- "
        f"bash -lc 'consul-dump-yaml --start-key \"customers/$CUSTOMER_ID/dbservers/{dbserver_id}\"'"
    )
    dbserver_dump = run_shell(cmd2, capture=True)
    if not dbserver_dump:
        print("⚠ consul-dump-yaml (dbserver details) returned nothing or failed.")
        print("Dropping to interactive shell inside resmgr pod. After you locate admin_pass, exit and paste it here.")
        run_shell(f"kubectl exec -it deploy/resmgr -c resmgr -n {ns} -- bash", interactive=True)
        admin_pass = input("Enter admin_pass (copied from inside pod): ").strip()
        if not admin_pass:
            print("❌ No admin_pass provided. Aborting.")
            return
    else:
        m2 = re.search(r"admin_pass:\s*(\S+)", dbserver_dump)
        if not m2:
            print("⚠ Could not parse admin_pass from dbserver output. Showing output:")
            print(dbserver_dump)
            print("Dropping to interactive shell inside resmgr pod for manual inspection.")
            run_shell(f"kubectl exec -it deploy/resmgr -c resmgr -n {ns} -- bash", interactive=True)
            admin_pass = input("Enter admin_pass (copied from inside pod): ").strip()
            if not admin_pass:
                print("❌ No admin_pass provided. Aborting.")
                return
        else:
            admin_pass = m2.group(1)
            # store but do NOT print
            os.environ["ADMIN_PASS"] = admin_pass
            print("✅ admin_pass retrieved and stored in $ADMIN_PASS (not displayed).")

    # 6) ask for host id
    host_id = input("Enter host ID: ").strip()
    if not host_id:
        print("❌ host ID required")
        return

    # 7) run mysql query inside mysqld-exporter using admin_pass
    query = f"SELECT id,hostname,responding FROM hosts WHERE id='{host_id}';"
    mysql_cmd_list = [
        "kubectl", "exec", "-n", ns, "deploy/mysqld-exporter", "-c", "mysqld-exporter",
        "--", "mysql", "resmgr", "-u", "root", f"-p{admin_pass}", "-e", query
    ]
    out = run_list(mysql_cmd_list, capture=True)
    if out is None:
        print("❌ MySQL command failed. Possible causes: wrong admin_pass, mysql not reachable, or permissions.")
        return
    print("\n✅ Query result:")
    lines = [line for line in out.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        print("(no rows)")
        return
    headers = lines[0].split()
    rows = [line.split() for line in lines[1:]]
    col_widths = [max(len(str(item)) for item in [header] + [row[i] for row in rows]) for i, header in enumerate(headers)]
    def format_row(row):
        return " | ".join(str(item).ljust(col_widths[i]) for i, item in enumerate(row))
    print(format_row(headers))
    print("-+-".join('-' * w for w in col_widths))
    for row in rows:
        print(format_row(row))

# -----------------------
# main
# -----------------------
def main():
    print("Select Product:")
    print("1. PMK")
    print("2. PMO")
    print("3. PCD")
    choice = input("Enter choice (1/2/3): ").strip()
    if choice == "1":
        print()
        print("\033[1m\033[34mPlease ensure you have KUBECONFIG exported with absolute path.\033[0m")
        print()
        handle_pmk()
    elif choice == "2":
        handle_pmo()
    elif choice == "3":
        handle_pcd()
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()
