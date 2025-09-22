**Host Disconnected Checker**
This script is an interactive troubleshooting tool for checking the status of hosts in three environments: PMK, PMO, and PCD. It automates manual steps and guides users through authentication, Kubernetes, AWS, and MySQL queries to quickly diagnose host connectivity issues.

**Features**
**PMK:**
Prompts for Kubernetes namespace and host ID
Finds the relevant pod and runs a MySQL query to display host status in a table

**PMO:**
Prompts for FQDN and host ID
Connects via SSH and runs remote commands to display host info

**PCD:**
Prompts for AWS region, performs SAML login, and updates kubeconfig
Fetches database server info from Consul
Retrieves admin password and runs a MySQL query to display host status in a table

**Prerequisites**
- Python 3 (3.6+)
- System tools: kubectl, ssh, saml2aws, aws CLI
- KUBECONFIG exported with absolute path.
- Access to relevant Kubernetes clusters and AWS accounts

**Usage**

```python
python3 test4-host-dc-checker.py
```

Follow the interactive prompts to check host status in your environment.

Feel free to suggest feature enhancements.