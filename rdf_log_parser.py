"""
Evolution Renewal Download Failure Log Parser
Usage:
  python rdf_log_parser.py <path_to_output_date_folder>
  python rdf_log_parser.py output/20260604

Parses Job 1 & Job 2 logs, extracts errors, classifies them, suggests actions.
Reads Confluence history for known error resolutions.
Output: rdf_result_<date>.txt
"""

import sys
import os
import re
import json
import urllib.request
import urllib.error
import ssl
from datetime import datetime

# --- CONFIG ---
MCP_ENV_PATH = os.path.expanduser('~/.config/mcp/env.wsl')
if not os.path.exists(MCP_ENV_PATH):
    MCP_ENV_PATH = '/mnt/c/Users/gaok/.config/mcp/env.wsl'
CONFLUENCE_PAGE_IDS = {
    '2020': '1813032386',
    '2021': '1813032562',
    '2022': '1818263765',
    '2023': '1818263798',
    '2024': '1818274512',
    '2025': '1884144292',
    '2026': '2434894460',
}
KNOWLEDGE_BASE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'error_knowledge_base.json')

# Error classification and suggested actions
ERROR_ACTIONS = {
    'INVALID_AGENT': 'Email to Antonietta (eBusiness support)',
    'PolicyInForce': 'No action needed - policy already in force',
    'INVALID_SUNRISE_FOLDER_RANGE': 'Need to send as Import',
    'CONTRACT_NOT_FOUND': 'Reference mismatch due to discard. Need to send as Import',
    'INVITE_RENEWAL_NOT_CLOSED': 'Previous renewal has not been closed. Need to send as Import',
    'INVITE_RENEWAL_CANCELLED': 'Check POLISY if cancelled. If cancelled, no action',
    'INVALID_BIND_STATE': 'Check POLISY if renewed. If renewed, no action',
    'DATABASE_ERROR': 'Retry - raise to I&O if persistent',
    'UNKNOWN': 'Investigate manually',
}


def load_confluence_config():
    """Load Confluence URL and token from MCP env file"""
    config = {}
    if os.path.exists(MCP_ENV_PATH):
        with open(MCP_ENV_PATH, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    config[key.strip()] = val.strip()
    return config


def confluence_get_page(page_id, config):
    """Read a Confluence page content via REST API"""
    url = f"{config['CONFLUENCE_URL']}/rest/api/content/{page_id}?expand=body.storage"
    req = urllib.request.Request(url)
    req.add_header('Authorization', f"Bearer {config['CONFLUENCE_PERSONAL_TOKEN']}")
    req.add_header('Accept', 'application/json')

    ctx = ssl.create_default_context()
    if config.get('CONFLUENCE_SSL_VERIFY', 'true').lower() == 'false':
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('body', {}).get('storage', {}).get('value', '')
    except Exception as e:
        print(f"  WARNING: Cannot read Confluence page {page_id}: {e}")
        return ''


def build_knowledge_base(config):
    """Read all Confluence pages and build error-pattern-based knowledge base"""
    print("Building knowledge base from Confluence...")
    # Start with the known error patterns
    kb = {
        "INVALID_AGENT": {"pattern": "agent .* is invalid or expired|cannot load the agent", "action": "Email to Antonietta (eBusiness support)", "notes": "INVALID_AGENT - agent number expired or invalid", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "POLICY_IN_FORCE": {"pattern": "policyinforce|already in force.*import data has been rejected", "action": "No action needed - policy already in force", "notes": "Policy already renewed/active", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "INVALID_SUNRISE_FOLDER_RANGE": {"pattern": "folderrange|invalid_sunrise_folder_range|problem on getting sunrise folderrange", "action": "Need to send as Import", "notes": "FolderRange error from Sunrise TE", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "CONTRACT_NOT_FOUND": {"pattern": "contract .* not found|contract_not_found", "action": "Reference mismatch due to discard. Need to send as Import", "notes": "TDX server contract reference mismatch", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "INVITE_RENEWAL_NOT_CLOSED": {"pattern": "inviterenewal.*not permitted.*contract has not been closed", "action": "Need to send as Import", "notes": "Previous renewal not closed", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "INVITE_RENEWAL_CANCELLED": {"pattern": "inviterenewal.*not permitted.*terminated.*cancelled|cancelled or lapsed", "action": "Check POLISY if cancelled. If cancelled, no action", "notes": "Contract terminated/cancelled/lapsed", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "INVALID_BIND_STATE": {"pattern": "invalid bind state.*ready.*bound", "action": "Check POLISY if renewed. If renewed, no action", "notes": "Bind state mismatch", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
        "DATABASE_ERROR": {"pattern": "database.*error|cannot open connection|cannot_connect_jdbc", "action": "Retry - raise to I&O if persistent", "notes": "Database connection failure", "occurrences": 0, "last_seen": "", "example_actions_taken": []},
    }

    for year, page_id in CONFLUENCE_PAGE_IDS.items():
        print(f"  Reading {year}...")
        html = confluence_get_page(page_id, config)
        if not html:
            continue

        # Count occurrences of each pattern in the page
        for key, entry in kb.items():
            matches = re.findall(entry['pattern'], html, re.IGNORECASE)
            if matches:
                entry['occurrences'] += len(matches)
                entry['last_seen'] = year

        # Extract action_taken entries to enrich example_actions_taken
        actions = re.findall(r'Email sent to\s+Antonietta', html, re.IGNORECASE)
        if actions:
            kb['INVALID_AGENT']['example_actions_taken'] = list(set(kb['INVALID_AGENT'].get('example_actions_taken', []) + ['Email sent to Antonietta']))

        imports = re.findall(r'(?:Send|sent|done).*[Ii]mport', html)
        if imports:
            kb['INVALID_SUNRISE_FOLDER_RANGE']['example_actions_taken'] = list(set(kb['INVALID_SUNRISE_FOLDER_RANGE'].get('example_actions_taken', []) + ['Send as Import']))
            kb['CONTRACT_NOT_FOUND']['example_actions_taken'] = list(set(kb['CONTRACT_NOT_FOUND'].get('example_actions_taken', []) + ['Retry by importing/sending again']))

    with open(KNOWLEDGE_BASE_FILE, 'w') as f:
        json.dump(kb, f, indent=2)
    print(f"  Saved {len(kb)} error patterns to {KNOWLEDGE_BASE_FILE}")
    return kb


def load_knowledge_base(config=None):
    """Load knowledge base from file or build from Confluence"""
    if os.path.exists(KNOWLEDGE_BASE_FILE):
        with open(KNOWLEDGE_BASE_FILE, 'r') as f:
            return json.load(f)
    elif config and config.get('CONFLUENCE_PERSONAL_TOKEN'):
        return build_knowledge_base(config)
    return {}


def lookup_history(policy, agent, category, kb):
    """Check knowledge base for known error pattern and return historical action"""
    if not kb:
        return None

    for key, entry in kb.items():
        if key == category or key == category.upper():
            actions = entry.get('example_actions_taken', [])
            action_str = entry.get('action', 'Unknown')
            count = entry.get('occurrences', 0)
            last = entry.get('last_seen', '?')
            examples = ', '.join(actions[:2]) if actions else ''
            result = f"KNOWN error type (seen {count}x, last {last}). Action: {action_str}"
            if examples:
                result += f" | Past actions: {examples}"
            return result

    return "NEW error type - not seen in Confluence history. Investigate manually."


def classify_error(error_msg, kb=None):
    """Classify error message by matching against patterns from knowledge base JSON"""
    msg = error_msg.lower()
    agent = None

    # Try matching from knowledge base patterns first
    if kb:
        for key, entry in kb.items():
            pattern = entry.get('pattern', '')
            if not pattern:
                continue
            try:
                if re.search(pattern, msg, re.IGNORECASE):
                    # Extract agent number if it's an agent error
                    if 'agent' in key.lower() or 'invalid_agent' in key.lower():
                        agent_match = re.search(r"agent[^\w]*'?([A-Z]\d{5,15})'?", error_msg, re.IGNORECASE)
                        agent = agent_match.group(1) if agent_match else 'unknown'
                    action = entry.get('action', 'Investigate manually')
                    note = entry.get('notes', msg[:100])
                    if agent:
                        note = f"INVALID_AGENT {agent}"
                    return key, note, action, agent
            except re.error:
                continue

    # Fallback: hardcoded matching if KB not loaded or no match
    if 'invalid or expired' in msg or 'cannot load the agent' in msg:
        agent_match = re.search(r"agent[^\w]*'?([A-Z]\d{5,15})'?", error_msg, re.IGNORECASE)
        agent = agent_match.group(1) if agent_match else 'unknown'
        return 'INVALID_AGENT', f"INVALID_AGENT {agent}", 'Email to Antonietta (eBusiness support)', agent
    elif 'policyinforc' in msg or 'already in force' in msg:
        return 'POLICY_IN_FORCE', 'Policy already in force', 'No action needed - policy already in force', None
    elif 'folderrange' in msg or 'invalid_sunrise_folder_range' in msg:
        return 'INVALID_SUNRISE_FOLDER_RANGE', 'FolderRange error from Sunrise TE', 'Need to send as Import', None
    elif 'contract' in msg and 'not found' in msg:
        return 'CONTRACT_NOT_FOUND', 'Contract not found (reference mismatch)', 'Reference mismatch due to discard. Need to send as Import', None
    elif 'inviterenewal' in msg and 'not been closed' in msg:
        return 'INVITE_RENEWAL_NOT_CLOSED', 'InviteRenewal not permitted - contract not closed', 'Need to send as Import', None
    elif ('inviterenewal' in msg or 'not permitted' in msg) and ('cancelled' in msg or 'lapsed' in msg or 'terminated' in msg):
        return 'INVITE_RENEWAL_CANCELLED', 'Contract terminated/cancelled/lapsed', 'Check POLISY if cancelled. If cancelled, no action', None
    elif 'invalid bind state' in msg:
        return 'INVALID_BIND_STATE', 'Invalid bind state (Ready vs Bound)', 'Check POLISY if renewed. If renewed, no action', None
    elif 'database' in msg or 'cannot open connection' in msg or 'cannot_connect_jdbc' in msg:
        return 'DATABASE_ERROR', 'Database connection error', 'Retry - raise to I&O if persistent', None
    elif 'failed to commicate' in msg or 'te_error' in msg or 'the request to the t' in msg:
        # TE wrapper without nested exception resolved - check for sub-patterns
        if 'contract' in msg and 'not found' in msg:
            return 'CONTRACT_NOT_FOUND', 'Contract not found (reference mismatch)', 'Reference mismatch due to discard. Need to send as Import', None
        elif 'policyinforc' in msg or 'already in force' in msg:
            return 'POLICY_IN_FORCE', 'Policy already in force', 'No action needed - policy already in force', None
        elif 'not been closed' in msg:
            return 'INVITE_RENEWAL_NOT_CLOSED', 'InviteRenewal not permitted - contract not closed', 'Need to send as Import', None
        elif 'invalid bind state' in msg:
            return 'INVALID_BIND_STATE', 'Invalid bind state (Ready vs Bound)', 'Check POLISY if renewed. If renewed, no action', None
        else:
            return 'TE_ERROR', 'Transaction Engine communication error', 'Retry by importing/sending again', None
    else:
        # Try LLM investigation for truly unknown errors
        llm_result = llm_investigate(error_msg)
        if llm_result:
            return llm_result
        return 'UNKNOWN', error_msg[:100], 'Investigate manually', None


def llm_investigate(error_msg):
    """Use Kiro CLI to analyze unknown errors against nevo source code"""
    import subprocess
    import shutil

    # Check if kiro-cli is available (directly or via WSL)
    kiro_cmd = None
    if shutil.which('kiro-cli'):
        kiro_cmd = ['kiro-cli', 'chat', '--no-interactive', '--trust-all-tools']
    elif os.name == 'nt' and shutil.which('wsl'):
        kiro_cmd = ['wsl', 'kiro-cli', 'chat', '--no-interactive', '--trust-all-tools']
    else:
        return None

    # Extract class and line from stack trace
    class_match = re.search(r'at ([\w.]+)\((\w+\.java):(\d+)\)', error_msg)
    code_context = ""
    if class_match:
        full_class = class_match.group(1)
        filename = class_match.group(2)
        line_num = class_match.group(3)
        # Try to fetch source from nevo repo
        code_context = fetch_source_from_repo(full_class, filename, line_num)

    prompt = f"""You are analyzing an Evolution Renewal Download Failure error.

Known error categories and actions:
- INVALID_AGENT: agent expired/invalid → Email to Antonietta (eBusiness support)
- POLICY_IN_FORCE: policy already renewed → No action needed
- INVALID_SUNRISE_FOLDER_RANGE: FolderRange error → Need to send as Import
- CONTRACT_NOT_FOUND: contract reference mismatch → Need to send as Import
- INVITE_RENEWAL_NOT_CLOSED: previous renewal not closed → Need to send as Import
- INVITE_RENEWAL_CANCELLED: contract cancelled/lapsed → Check POLISY, if cancelled no action
- INVALID_BIND_STATE: bind state mismatch → Check POLISY, if renewed no action
- DATABASE_ERROR: DB connection failure → Retry, raise to I&O if persistent
- TE_ERROR: Transaction Engine communication error → Retry by importing/sending again

Error message:
{error_msg[:500]}

{code_context}

Based on the error and code, respond in EXACTLY this format (one line):
CATEGORY|short description|recommended action

If it matches a known category, use that. If truly new, use UNKNOWN|description|suggested action."""

    try:
        result = subprocess.run(
            kiro_cmd + [prompt],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and '|' in result.stdout:
            # Strip ANSI escape codes from output
            clean_output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()
            # Find the line with CATEGORY|note|action format
            for line in reversed(clean_output.split('\n')):
                line = line.strip().lstrip('> ').strip()
                if '|' in line and len(line.split('|')) >= 3:
                    parts = line.split('|')
                    category = parts[0].strip()
                    note = parts[1].strip()
                    action = parts[2].strip()
                    return category, note, action, None
    except subprocess.TimeoutExpired:
        print("  [LLM] Kiro CLI timed out (>60s)")
    except FileNotFoundError:
        print("  [LLM] kiro-cli not found on PATH")
    except Exception as e:
        print(f"  [LLM] Error calling kiro-cli: {e}")
    return None


def fetch_source_from_repo(full_class, filename, line_num):
    """Fetch relevant source code from aztau-java/nevo repo via GitHub API"""
    import urllib.request
    import json
    import ssl

    # Convert class path to file search
    # e.g., au.com.allianz.evolution.sunrise.download.ProcessDownloadFile -> search for ProcessDownloadFile.java
    package_path = full_class.rsplit('.', 1)[0].replace('.', '/')
    search_paths = [
        f"nevo-services/evorenewals/src/main/java/{package_path}/{filename}",
        f"nevo-services/nevo-services-renewal/src/main/java/{package_path}/{filename}",
        f"nevo-services/framework/src/main/java/{package_path}/{filename}",
        f"nevo-services/evocore/src/main/java/{package_path}/{filename}",
    ]

    # Try GitHub Enterprise API
    token = os.environ.get('GITHUB_ENTERPRISE_TOKEN', '')
    if not token:
        # Try reading from git config or MCP env
        mcp_env = os.path.expanduser('~/.config/mcp/env.wsl')
        if os.path.exists(mcp_env):
            with open(mcp_env, 'r') as f:
                for line in f:
                    if 'GITHUB' in line and 'TOKEN' in line and '=' in line:
                        token = line.split('=', 1)[1].strip()
                        break

    if not token:
        return ""

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for path in search_paths:
        url = f"https://github.developer.allianz.io/api/v3/repos/aztau-java/nevo/contents/{path}"
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'token {token}')
        req.add_header('Accept', 'application/vnd.github.v3.raw')
        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
                source = resp.read().decode('utf-8')
                # Extract lines around the error line
                lines = source.split('\n')
                ln = int(line_num)
                start = max(0, ln - 10)
                end = min(len(lines), ln + 10)
                snippet = '\n'.join(f"{i+1}: {lines[i]}" for i in range(start, end))
                return f"\nRelevant source code ({filename} around line {line_num}):\n```java\n{snippet}\n```"
        except:
            continue

    return ""


def find_job_folders(date_folder):
    """Find Job 1 and Job 2 folders within a date folder"""
    job1 = None
    job2 = None
    subfolders = sorted([d for d in os.listdir(date_folder) if os.path.isdir(os.path.join(date_folder, d))])

    for sf in subfolders:
        sf_path = os.path.join(date_folder, sf)
        if os.path.exists(os.path.join(sf_path, 'RDFoutput')):
            job1 = sf_path
        elif os.path.exists(os.path.join(sf_path, 'evolution.log')):
            job2 = sf_path

    return job1, job2


def get_input_count(input_folder):
    """Get total record count from input REGP.M1.EDI.DOWNLOAD file"""
    for root, dirs, files in os.walk(input_folder):
        for f in files:
            if f == 'REGP.M1.EDI.DOWNLOAD':
                filepath = os.path.join(root, f)
                last_count = None
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as fh:
                    for line in fh:
                        match = re.search(r'\*+COUNT\s+(\d+)', line)
                        if match:
                            last_count = int(match.group(1))
                return last_count
    return None


def parse_job1_log(job1_folder):
    """Parse Job 1 log to get saved count"""
    log_path = os.path.join(job1_folder, 'log', 'evolution.log')
    if not os.path.exists(log_path):
        log_path = os.path.join(job1_folder, 'evolution.log')
    if not os.path.exists(log_path):
        return 0

    count = 0
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if '>>>>> Saving renewalTxn item:' in line:
                count += 1
    return count


def parse_job2_log(job2_folder):
    """Parse Job 2 log to get processed count and errors"""
    log_path = os.path.join(job2_folder, 'evolution.log')
    if not os.path.exists(log_path):
        return 0, []

    errors = []

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Count processed
    processed = content.count('***End RDF policy***')

    # Only count REAL errors: "ProcessDownloadFile  - Sending email>>>>"
    # NOT "RdfUtil  - Sending email>>>>" which is just the report email
    real_error_count = len(re.findall(r'ProcessDownloadFile\s+-\s+Sending email>>>>', content))

    if real_error_count == 0:
        return processed, []

    # Extract errors from failedDownloadBasic.log
    basic_log = os.path.join(job2_folder, 'failedDownloadBasic.log')
    if os.path.exists(basic_log):
        with open(basic_log, 'r', encoding='utf-8', errors='ignore') as f:
            basic_content = f.read().strip()

        if basic_content and not basic_content.startswith('***') and 'EOF' not in basic_content[:20]:
            # Pattern: "PolicyNumber : XXXXX. Message :..."
            policy_errors = re.findall(r'PolicyNumber\s*:\s*(\S+?)\.?\s*(?:\.|,)?\s*Message\s*:(.*?)(?=\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.*?PolicyNumber|$)', basic_content, re.DOTALL)
            if policy_errors:
                for policy, msg in policy_errors:
                    full_msg = msg.strip()[:500]
                    if 'unknown error' in full_msg.lower() or 'failed to commicate' in full_msg.lower():
                        # Look for nested exception within this policy's block
                        nested = re.search(r'-Nested Exception:.*?:\s*(.*?)(?:\[|$)', full_msg)
                        if nested:
                            full_msg = nested.group(1).strip()[:200]
                        else:
                            # Fallback: look for error codes
                            code_match = re.search(r'::([A-Z_]+)::\d+', full_msg)
                            if code_match and code_match.group(1) not in ('UNKNOWN_ERROR', 'TE_ERROR'):
                                full_msg = code_match.group(1)
                    else:
                        # Take just the first line of the message
                        full_msg = full_msg.split('\n')[0].strip()[:300]
                    errors.append({'policy': policy.strip().rstrip('.'), 'message': full_msg})

    # Fallback: parse evolution.log for errors if basic log didn't have them
    if not errors and real_error_count > 0:
        # Find policies that triggered ProcessDownloadFile error emails
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'ProcessDownloadFile' in line and 'Sending email>>>>' in line:
                # Look backwards for "Transactions found = POLICY"
                for j in range(max(0, i-20), i):
                    tmatch = re.search(r'Transactions found = (\S+)', lines[j])
                    if tmatch:
                        policy = tmatch.group(1)
                        # Look for error message nearby
                        err_msg = 'Unknown error'
                        for k in range(max(0, i-10), i):
                            ematch = re.search(r'DownloadProcessingException:\s*(.*?)(?:\[|$)', lines[k])
                            if ematch:
                                err_msg = ematch.group(1).strip()[:200]
                                break
                        errors.append({'policy': policy, 'message': err_msg})
                        break

    return processed, errors


def parse_date_folder(date_folder, input_folder=None, kb=None):
    """Parse a single date's output folder"""
    date_str = os.path.basename(date_folder)

    job1, job2 = find_job_folders(date_folder)

    # Get counts
    input_count = None
    if input_folder and os.path.exists(input_folder):
        input_count = get_input_count(input_folder)

    job1_count = parse_job1_log(job1) if job1 else 0
    processed, errors = parse_job2_log(job2) if job2 else (0, [])

    total_records = input_count or job1_count or processed
    if total_records == 0:
        total_records = processed

    # Verify counts match
    count_mismatch = None
    if input_count and job1_count and input_count != job1_count:
        count_mismatch = f"INPUT({input_count}) != JOB1({job1_count})"
    if input_count and processed and input_count != processed:
        count_mismatch = f"INPUT({input_count}) != JOB2({processed})"

    # Classify errors
    classified_errors = []
    for err in errors:
        category, note, action, agent = classify_error(err['message'], kb)
        classified_errors.append({
            'policy': err['policy'],
            'message': err['message'],
            'category': category,
            'note': note,
            'action': action,
            'agent': agent,
        })

    return {
        'date': date_str,
        'total_records': total_records,
        'input_count': input_count,
        'job1_count': job1_count,
        'job2_count': processed,
        'count_mismatch': count_mismatch,
        'error_count': len(classified_errors),
        'errors': classified_errors,
    }


def format_output(result, kb=None):
    """Format result as text for review"""
    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"Evolution Renewal Download - {result['date']}")
    lines.append(f"{'='*70}")
    lines.append(f"")
    lines.append(f"Records Processed: {result['total_records']}")
    if result.get('input_count') and result.get('job2_count'):
        lines.append(f"  Input Count:  {result['input_count']}")
        lines.append(f"  Job 1 Count:  {result['job1_count']}")
        lines.append(f"  Job 2 Count:  {result['job2_count']}")
    if result.get('count_mismatch'):
        lines.append(f"  *** COUNT MISMATCH: {result['count_mismatch']} ***")
    lines.append(f"Error Records:     {result['error_count']}")
    lines.append(f"")

    if result['errors']:
        lines.append(f"{'─'*70}")
        lines.append(f"ERRORS:")
        lines.append(f"{'─'*70}")
        for i, e in enumerate(result['errors'], 1):
            lines.append(f"")
            lines.append(f"  {i}. Policy: {e['policy']}")
            lines.append(f"     Category: {e['category']}")
            lines.append(f"     Note: {e['note']}")
            lines.append(f"     Resolution: {e['action']}")
            # Knowledge base lookup
            if kb:
                history = lookup_history(e['policy'], e.get('agent'), e['category'], kb)
                if history:
                    lines.append(f"     History: {history}")
                else:
                    lines.append(f"     History: NEW - not seen before")
        lines.append(f"")
    else:
        lines.append(f"  No errors - all records processed successfully.")
        lines.append(f"")

    # Confluence table
    lines.append(f"{'─'*70}")
    lines.append(f"CONFLUENCE TABLE (columnar view):")
    lines.append(f"{'─'*70}")

    date_formatted = datetime.strptime(result['date'], '%Y%m%d').strftime('%d-%m-%Y') if len(result['date']) == 8 else result['date']

    lines.append(f"Date                    : {date_formatted}")
    lines.append(f"Records Processed       : {result['total_records']}")
    lines.append(f"Error Records           : {result['error_count']}")

    if result['errors']:
        lines.append(f"")
        lines.append(f"{'No':<4} {'Policy#':<20} {'Error Message':<45} {'Notes'}")
        lines.append(f"{'─'*4} {'─'*20} {'─'*45} {'─'*35}")
        for i, e in enumerate(result['errors'], 1):
            lines.append(f"{i:<4} {e['policy']:<20} {e['note']:<45} {e['action']}")

    lines.append(f"")
    lines.append(f"{'─'*70}")
    lines.append(f"CONFLUENCE ROW (copy-paste):")
    lines.append(f"{'─'*70}")

    if result['errors']:
        policies = '  '.join([f"{i+1}.{e['policy']}" for i, e in enumerate(result['errors'])])
        error_msgs = '  '.join([f"{i+1}.{e['note']}" for i, e in enumerate(result['errors'])])
        notes = '  '.join([f"{i+1}.{e['action']}" for i, e in enumerate(result['errors'])])
        lines.append(f"| {date_formatted} | {result['total_records']} | {result['error_count']} | {policies} | {error_msgs} | {notes} |  |")
    else:
        lines.append(f"| {date_formatted} | {result['total_records']} | 0 |  |  |  |  |")

    lines.append(f"")
    return '\n'.join(lines)


def agent_mode(config):
    """Interactive agent mode - parse, review, approve, post"""
    kb = load_knowledge_base(config)
    if kb:
        print(f"[Agent] Loaded {len(kb)} error patterns from knowledge base")

    print("\n╔══════════════════════════════════════════════════╗")
    print("║   RDF Log Parser - Agent Mode                    ║")
    print("║   Type a date (e.g. 20260116) or 'all' for batch ║")
    print("║   Type 'quit' to exit                            ║")
    print("╚══════════════════════════════════════════════════╝\n")

    while True:
        user_input = input("[Agent] Enter date folder (or 'all' / 'quit'): ").strip()

        if user_input.lower() in ('quit', 'exit', 'q'):
            print("[Agent] Bye!")
            break

        # Determine path
        if user_input.lower() == 'all':
            path = 'output'
        else:
            path = os.path.join('output', user_input)

        if not os.path.exists(path):
            print(f"[Agent] ERROR: Path not found: {path}")
            continue

        # Parse
        print(f"[Agent] Parsing {path}...")
        subfolders = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
        has_timestamp_folders = any(re.match(r'^\d{6}$', d) for d in subfolders)

        results = []
        if has_timestamp_folders:
            parent = os.path.dirname(path)
            grandparent = os.path.dirname(parent)
            date_str = os.path.basename(path)
            input_folder = os.path.join(grandparent, 'input', date_str)
            result = parse_date_folder(path, input_folder, kb)
            results.append(result)
        elif user_input.lower() == 'all':
            date_folders = sorted([d for d in subfolders if re.match(r'^\d{8}$', d)])
            for date_dir in date_folders:
                date_path = os.path.join(path, date_dir)
                input_folder = os.path.join('input', date_dir)
                result = parse_date_folder(date_path, input_folder, kb)
                results.append(result)
        else:
            result = parse_date_folder(path, kb=kb)
            results.append(result)

        # Show results
        for result in results:
            print(format_output(result, kb))

        # Ask for approval
        if config.get('CONFLUENCE_PERSONAL_TOKEN'):
            approval = input("\n[Agent] Post to Confluence? (yes/no): ").strip().lower()
            if approval in ('yes', 'y'):
                page_id = CONFLUENCE_PAGE_IDS.get('2026', '')
                if page_id:
                    post_confluence_comment(page_id, results, config)
            else:
                print("[Agent] Skipped posting. Result saved to file only.")
        else:
            print("[Agent] No Confluence token configured. Result saved to file only.")

        # Save to file
        if results:
            first_date = results[0]['date']
            last_date = results[-1]['date'] if len(results) > 1 else first_date
            output_file = f"rdf_result_{first_date}_{last_date}.txt" if first_date != last_date else f"rdf_result_{first_date}.txt"
        else:
            output_file = "rdf_result.txt"

        output_path = os.path.join('output', output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            for result in results:
                f.write(format_output(result, kb))
        print(f"[Agent] Saved to: {output_path}\n")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nOptions:")
        print("  --rebuild-kb    Force rebuild knowledge base from Confluence")
        print("  --agent         Interactive agent mode (parse, review, approve, post)")
        sys.exit(1)

    # Load Confluence config
    config = load_confluence_config()

    # Check for rebuild flag
    if '--rebuild-kb' in sys.argv:
        if config.get('CONFLUENCE_PERSONAL_TOKEN'):
            build_knowledge_base(config)
        else:
            print("ERROR: No Confluence token found in", MCP_ENV_PATH)
        sys.exit(0)

    # Agent mode
    if '--agent' in sys.argv:
        agent_mode(config)
        return

    path = sys.argv[1]

    if not os.path.exists(path):
        print(f"ERROR: Path not found: {path}")
        sys.exit(1)

    # Load knowledge base
    kb = load_knowledge_base(config)
    if kb:
        print(f"Loaded {len(kb)} entries from knowledge base")

    # Determine if single date or multiple
    subfolders = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    has_timestamp_folders = any(re.match(r'^\d{6}$', d) for d in subfolders)

    results = []

    if has_timestamp_folders:
        # Single date folder
        parent = os.path.dirname(path)
        grandparent = os.path.dirname(parent)
        date_str = os.path.basename(path)
        input_folder = os.path.join(grandparent, 'input', date_str)
        result = parse_date_folder(path, input_folder, kb)
        results.append(result)
    else:
        # Multiple date folders
        date_folders = sorted([d for d in subfolders if re.match(r'^\d{8}$', d)])
        for date_dir in date_folders:
            date_path = os.path.join(path, date_dir)
            parent = os.path.dirname(path)
            input_folder = os.path.join(parent, 'input', date_dir)
            result = parse_date_folder(date_path, input_folder, kb)
            results.append(result)

    # Output
    output_lines = []
    for result in results:
        output_lines.append(format_output(result, kb))

    output_text = '\n'.join(output_lines)
    print(output_text)

    # Save to file
    if results:
        first_date = results[0]['date']
        last_date = results[-1]['date'] if len(results) > 1 else first_date
        output_file = f"rdf_result_{first_date}_{last_date}.txt" if first_date != last_date else f"rdf_result_{first_date}.txt"
    else:
        output_file = "rdf_result.txt"

    output_path = os.path.join(os.path.dirname(path) if has_timestamp_folders else path, output_file)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_text)
    print(f"\nSaved to: {output_path}")

    # Post to Confluence as comment if requested
    if '--post' in sys.argv and config.get('CONFLUENCE_PERSONAL_TOKEN'):
        page_id = CONFLUENCE_PAGE_IDS.get('2026', '')
        if page_id:
            post_confluence_comment(page_id, results, config)


def post_confluence_comment(page_id, results, config):
    """Post results as a table comment on the Confluence page"""
    # Build HTML table matching Confluence page format
    rows = []
    for result in results:
        date_formatted = datetime.strptime(result['date'], '%Y%m%d').strftime('%d-%m-%Y') if len(result['date']) == 8 else result['date']
        if result['errors']:
            policies = '<br/>'.join([f"{i+1}.{e['policy']}" for i, e in enumerate(result['errors'])])
            error_msgs = '<br/>'.join([f"{i+1}.{e['note']}" for i, e in enumerate(result['errors'])])
            notes = '<br/>'.join([f"{i+1}.{e['action']}" for i, e in enumerate(result['errors'])])
        else:
            policies = ''
            error_msgs = ''
            notes = ''

        rows.append(
            f"<tr><td>{date_formatted}</td><td>{result['total_records']}</td>"
            f"<td>{result['error_count']}</td><td>{policies}</td>"
            f"<td>{error_msgs}</td><td>{notes}</td><td></td></tr>"
        )

    comment_html = (
        '<table><thead><tr><th>Date</th><th>Records</th>'
        '<th>Errors</th><th>Policy#</th>'
        '<th>Error Message</th><th>Notes</th><th>Action</th></tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody></table>'
    )

    ctx = ssl.create_default_context()
    if config.get('CONFLUENCE_SSL_VERIFY', 'true').lower() == 'false':
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    base_url = config['CONFLUENCE_URL'].rstrip('/')
    token = config['CONFLUENCE_PERSONAL_TOKEN']

    # Try multiple API approaches
    attempts = [
        (f"{base_url}/rest/api/content", {
            "type": "comment",
            "container": {"id": str(page_id), "type": "page"},
            "body": {"storage": {"value": comment_html, "representation": "storage"}}
        }),
        (f"{base_url}/rest/api/content/{page_id}/child/comment", {
            "type": "comment",
            "body": {"storage": {"value": comment_html, "representation": "storage"}}
        }),
        (f"{base_url}/rest/api/content/{page_id}/child/comment", {
            "body": {"storage": {"value": comment_html, "representation": "storage"}}
        }),
    ]

    for i, (url, payload) in enumerate(attempts, 1):
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f"Bearer {token}")
        req.add_header('Content-Type', 'application/json')
        req.add_header('X-Atlassian-Token', 'no-check')

        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
                print(f"\n✓ Comment posted to Confluence page {page_id}")
                return
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='ignore')[:200]
            print(f"  Attempt {i}: {e.code} {e.reason} [{url}] {body}")
        except Exception as e:
            print(f"  Attempt {i}: {e}")

    print(f"\n✗ All methods failed. Copy the result manually from the output file.")


if __name__ == '__main__':
    main()
