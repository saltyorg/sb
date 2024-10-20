import argparse
import os
import subprocess
import yaml
import sys
import shutil
import glob
import json
import shlex
import asyncio
import magic
import requests

################################
# Parse Saltbox accounts.yml
################################

saltbox_accounts_path = '/srv/git/saltbox/accounts.yml'


def validate_structure(dict_data):
    required_keys = {
        "user": ["domain", "email", "name", "pass"]
    }

    for key, subkeys in required_keys.items():
        if key not in dict_data:
            return False, f"Config file '{saltbox_accounts_path}' is missing required section: '{key}'"
        for subkey in subkeys:
            if subkey not in dict_data[key]:
                return False, f"Config file '{saltbox_accounts_path}' is missing required key '{subkey}' in section '{key}'"

    return True, "Valid structure"


try:
    with open(saltbox_accounts_path, 'r') as file:
        data = yaml.safe_load(file)
except FileNotFoundError:
    print(f"Error: Config file '{saltbox_accounts_path}' was not found.")
    sys.exit(1)
except yaml.YAMLError as e:
    print(f"Error parsing config file '{saltbox_accounts_path}': {e}")
    sys.exit(1)

# Check if the file is empty
if data is None:
    print(f"Error: Config file '{saltbox_accounts_path}' is empty.")
    sys.exit(1)

# Validate the structure of the parsed YAML
is_valid, message = validate_structure(data)
if not is_valid:
    print(f"Error: {message}")
    sys.exit(1)

################################
# Variables
################################

# Ansible
ANSIBLE_PLAYBOOK_BINARY_PATH = "/usr/local/bin/ansible-playbook"
CACHE_FILE = "/srv/git/sb/cache.json"

# Saltbox
SALTBOX_REPO_PATH = "/srv/git/saltbox"
SALTBOX_PLAYBOOK_PATH = f"{SALTBOX_REPO_PATH}/saltbox.yml"
SALTBOX_USER = data['user']['name']

# Sandbox
SANDBOX_REPO_PATH = "/opt/sandbox"
SANDBOX_PLAYBOOK_PATH = f"{SANDBOX_REPO_PATH}/sandbox.yml"

# Saltbox_mod
SALTBOXMOD_REPO_PATH = "/opt/saltbox_mod"
SALTBOXMOD_PLAYBOOK_PATH = f"{SALTBOXMOD_REPO_PATH}/saltbox_mod.yml"

# SB
SB_REPO_PATH = "/srv/git/sb"

__version__ = "0.0.0"


################################
# Functions
################################

def is_root():
    return os.geteuid() == 0


def relaunch_as_root():
    if not is_root():
        print("Relaunching with root privileges.")
        executable_path = os.path.abspath(sys.argv[0])
        try:
            # Attempt to relaunch the script with sudo
            subprocess.check_call(['sudo', executable_path] + sys.argv[1:])
        except subprocess.CalledProcessError as e:
            print(f"Failed to relaunch with root privileges: {e}")
        sys.exit(0)


def get_cached_tags(repo_path):
    """Retrieve cached tags and commit hash for the given repo_path."""
    try:
        with open(CACHE_FILE, "r") as cache_file:
            cache = json.load(cache_file)
        return cache.get(repo_path, {})
    except FileNotFoundError:
        return {}


def update_cache(repo_path, commit_hash, tags):
    """Update the cache with the new commit hash and tags."""
    try:
        with open(CACHE_FILE, "r") as cache_file:
            cache = json.load(cache_file)
    except FileNotFoundError:
        cache = {}
    cache[repo_path] = {"commit": commit_hash, "tags": tags}
    with open(CACHE_FILE, "w") as cache_file:
        json.dump(cache, cache_file)


def check_cache(repo_path, tags):
    cache = get_cached_tags(repo_path)
    if not cache:
        return True, []  # If cache doesn't exist, proceed with playbook execution

    cached_tags = set(cache.get("tags", []))
    requested_tags = set(tags)

    missing_tags = requested_tags - cached_tags
    return len(missing_tags) == 0, list(missing_tags)


def supports_color():
    """
    Returns True if the running system's terminal supports color,
    and False otherwise.
    """
    plat = sys.platform
    supported_platform = plat != 'Pocket PC' and (plat != 'win32' or 'ANSICON' in os.environ)

    # isatty is not always implemented, #6223.
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

    if not supported_platform or not is_a_tty:
        return False
    return True


class ColorPrinter:
    def __init__(self):
        self.use_color = supports_color()
        self.colors = {
            'red': '\033[91m',
            'green': '\033[92m',
            'yellow': '\033[93m',
            'blue': '\033[94m',
            'reset': '\033[0m'
        }

    def print_color(self, color, text):
        if self.use_color:
            print(f"{self.colors.get(color, '')}{text}{self.colors['reset']}")
        else:
            print(text)


def get_console_width(default=80):
    try:
        columns, _ = shutil.get_terminal_size()
    except AttributeError:
        columns = default
    return columns


def print_in_columns(tags, padding=2):
    if not tags:
        return

    console_width = shutil.get_terminal_size().columns
    max_tag_length = max(len(tag) for tag in tags) + padding
    num_columns = max(1, console_width // max_tag_length)  # Ensure at least one column
    num_rows = (len(tags) + num_columns - 1) // num_columns  # Ceiling division to ensure all tags are included

    for row in range(num_rows):
        for col in range(num_columns):
            idx = row + col * num_rows
            if idx < len(tags):
                print(f"{tags[idx]:{max_tag_length}}", end='')
        print()  # Newline after each row


def get_git_commit_hash(repo_path):
    """Get the current Git commit hash of the repository."""
    try:
        completed_process = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, stdout=subprocess.PIPE,
                                           text=True)
    except FileNotFoundError:
        print(f"\nThe folder '{repo_path}' does not exist. This indicates an incomplete install.\n")
        sys.exit(1)
    else:
        if completed_process.returncode != 0:
            print(f"Error occurred while trying to get the git commit hash: {completed_process.stderr}")
            sys.exit(completed_process.returncode)
        return completed_process.stdout.strip()


async def run_and_cache_ansible_tags(repo_path, playbook_path, extra_skip_tags):
    command, tag_parser = prepare_ansible_list_tags(repo_path, playbook_path, extra_skip_tags)
    if command:  # Need to fetch tags
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await process.communicate()
        output = stdout.decode()
        tag_parser(output)


def prepare_ansible_list_tags(repo_path, playbook_path, extra_skip_tags):
    def parse_output(output):
        try:
            task_tags_line = next(line for line in output.split('\n') if "TASK TAGS:" in line)
            task_tags = task_tags_line.split("TASK TAGS:")[1].replace('[', '').replace(']', '').strip()
            tags = [tag.strip() for tag in task_tags.split(',') if tag.strip()]
        except StopIteration:
            return (f"Error: 'TASK TAGS:' not found in the ansible-playbook output. Please make sure '{playbook_path}' "
                    f"is formatted correctly.")
        except Exception as e:
            return f"Error processing command output: {str(e)}"

        if repo_path != SALTBOXMOD_REPO_PATH:
            commit_hash = get_git_commit_hash(repo_path)
            update_cache(repo_path, commit_hash, tags)
        return tags

    if repo_path == SALTBOXMOD_REPO_PATH:
        command = [
            ANSIBLE_PLAYBOOK_BINARY_PATH,
            playbook_path,
            '--become',
            '--list-tags',
            f'--skip-tags=always,{extra_skip_tags}'
        ]
    else:
        cache = get_cached_tags(repo_path)
        current_commit = get_git_commit_hash(repo_path)
        if cache.get("commit") == current_commit:
            return None, lambda _: cache["tags"]  # Use cached tags
        command = [
            ANSIBLE_PLAYBOOK_BINARY_PATH,
            playbook_path,
            '--become',
            '--list-tags',
            f'--skip-tags=always,{extra_skip_tags}'
        ]

    return command, parse_output


async def handle_list_async():
    # Define repository information along with their base titles
    repo_info = [
        (SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, "", "Saltbox tags:"),
        (SANDBOX_REPO_PATH, SANDBOX_PLAYBOOK_PATH, "sanity_check", "\nSandbox tags (prepend sandbox-):"),
    ]

    # Add saltbox_mod conditionally
    if os.path.isdir(SALTBOXMOD_REPO_PATH):
        repo_info.append(
            (SALTBOXMOD_REPO_PATH, SALTBOXMOD_PLAYBOOK_PATH, "sanity_check", "\nSaltbox_mod tags (prepend mod-):"))

    for repo_path, playbook_path, extra_skip_tags, base_title in repo_info:
        command, tag_parser = prepare_ansible_list_tags(repo_path, playbook_path, extra_skip_tags)

        # Determine if cached values are used based on the presence of command
        cache_status = " (cached)" if command is None else ""

        if command:  # Fetch and parse tags if not using cache
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await process.communicate()
            tags = tag_parser(stdout.decode())
        else:  # Cached tags are available
            tags = tag_parser(None)  # Get cached tags directly

        # Construct the title with cache status using an f-string
        title_with_status = f"{base_title}{cache_status}\n"
        print(title_with_status)
        if isinstance(tags, str) and tags.startswith("Error"):
            print(tags)  # Print the error message directly
        else:
            print_in_columns(tags)


def handle_list(_arguments):
    asyncio.run(handle_list_async())


def handle_recreate_venv(_arguments):
    manage_ansible_venv(recreate=True)


def run_ansible_playbook(repo_path, playbook_path, ansible_binary_path, tags=None, skip_tags=None, verbosity=0,
                         extra_vars=None):
    command = [ansible_binary_path, playbook_path, "--become"]
    if tags:
        command += ["--tags", ','.join(tags)]
    if skip_tags:
        command += ["--skip-tags", ','.join(skip_tags)]
    if verbosity > 0:
        command.append('-' + 'v' * verbosity)
    if extra_vars:
        combined_extra_vars = {}
        file_extra_vars = []
        for var in extra_vars:
            if var.startswith("@"):
                # If the extra var starts with @, treat it as a file path and pass it directly
                file_extra_vars.append(var)
            else:
                try:
                    # Attempt to parse the entire var as JSON
                    parsed_var = json.loads(var)
                    if isinstance(parsed_var, dict):
                        combined_extra_vars.update(parsed_var)
                    else:
                        raise ValueError("The provided JSON is not a dictionary.")
                except json.JSONDecodeError:
                    if "=" in var:
                        key, value = var.split("=", 1)
                        try:
                            # Attempt to parse the value as JSON
                            parsed_value = json.loads(value, parse_float=str)
                        except json.JSONDecodeError:
                            # If JSON parsing fails, treat it as a plain string
                            parsed_value = value
                        combined_extra_vars[key] = parsed_value
                    else:
                        print(f"Error: Failed to parse '{var}' as valid JSON or a key=value pair.")
                        sys.exit(1)  # Exit the script with an error status

        # Add combined extra vars as a JSON string
        if combined_extra_vars:
            command += ["--extra-vars", json.dumps(combined_extra_vars)]

        # Add file-based extra vars
        for file_var in file_extra_vars:
            command += ["--extra-vars", file_var]

    print(f"Executing Ansible playbook with command: {' '.join(shlex.quote(arg) for arg in command)}")
    try:
        result = subprocess.run(command, cwd=repo_path)
    except KeyboardInterrupt:
        print(f"\nError: Playbook {playbook_path} run was aborted by the user.\n")
        sys.exit(1)
    if result.returncode != 0:
        print(f"\nError: Playbook {playbook_path} run failed, scroll up to the failed task to review.\n")
        sys.exit(result.returncode)
    print(f"\nPlaybook {playbook_path} executed successfully.\n")


def git_fetch_and_reset(repo_path, default_branch='master', post_fetch_script=None, custom_commands=None):
    # Get current branch name
    current_branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_path, stdout=subprocess.PIPE,
                                    text=True).stdout.strip()

    # Determine if a reset to default_branch is needed
    if current_branch != default_branch:
        print(f"Currently on branch '{current_branch}'.")
        reset_to_default = input(f"Do you want to reset to the '{default_branch}' branch? (y/n): ").strip().lower()
        if reset_to_default != 'y':
            # User chose not to reset to default_branch; fetch and reset the current branch instead
            print(f"Updating the current branch '{current_branch}'...")
            branch = current_branch
        else:
            # User chose to reset to default_branch
            branch = default_branch
    else:
        branch = default_branch

    # Commands to fetch and reset
    commands = [
        ['git', 'fetch', '--quiet'],
        ['git', 'clean', '--quiet', '-df'],
        ['git', 'reset', '--quiet', '--hard', '@{u}'],
        ['git', 'checkout', '--quiet', branch],
        ['git', 'clean', '--quiet', '-df'],
        ['git', 'reset', '--quiet', '--hard', '@{u}'],
        ['git', 'submodule', 'update', '--init', '--recursive'],
        ['chown', '-R', f'{SALTBOX_USER}:{SALTBOX_USER}', repo_path]
    ]

    for command in commands:
        subprocess.run(command, cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if post_fetch_script:
        subprocess.run(post_fetch_script, shell=True, cwd=repo_path, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

    if custom_commands:
        for command in custom_commands:
            subprocess.run(command, shell=True, cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"Repository at {repo_path} has been updated. Current branch: '{branch}'.")


def version_compare(v1, v2):
    """
    Compare two version strings.
    :return: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    v1_parts = v1.lstrip('v').split('.')
    v2_parts = v2.lstrip('v').split('.')

    for i in range(max(len(v1_parts), len(v2_parts))):
        v1_part = int(v1_parts[i]) if i < len(v1_parts) else 0
        v2_part = int(v2_parts[i]) if i < len(v2_parts) else 0

        if v1_part < v2_part:
            return -1
        elif v1_part > v2_part:
            return 1

    return 0


def download_and_install_saltbox_fact(always_update=False):
    download_url = "https://github.com/saltyorg/ansible-facts/releases/latest/download/saltbox-facts"
    target_path = "/srv/git/saltbox/ansible_facts.d/saltbox.fact"

    try:
        # Fetch the latest release info from GitHub
        response = requests.get("https://api.github.com/repos/saltyorg/ansible-facts/releases/latest")
        response.raise_for_status()
        latest_release = response.json()
        latest_version = latest_release['tag_name']

        if os.path.exists(target_path) and not always_update:
            # Run the existing saltbox.fact and parse its output
            result = subprocess.run([target_path], capture_output=True, text=True)
            if result.returncode == 0:
                try:
                    current_data = json.loads(result.stdout)
                    current_version = current_data.get("saltbox_facts_version")

                    if current_version is None:
                        print("Current saltbox.fact doesn't have version info. Updating...")
                    elif version_compare(current_version, latest_version) >= 0:
                        print(f"saltbox.fact is up to date (version {current_version})")
                        return
                    else:
                        print(f"New version available. Updating from {current_version} to {latest_version}")
                except json.JSONDecodeError:
                    print("Failed to parse current saltbox.fact output. Proceeding with update.")
            else:
                print("Failed to run current saltbox.fact. Proceeding with update.")
        else:
            if always_update:
                print("Update forced. Proceeding with update.")
            else:
                print("saltbox.fact not found. Proceeding with update.")

        print(f"Updating saltbox.fact to version {latest_version}")

        response = requests.get(download_url)
        response.raise_for_status()

        # Ensure the directory exists
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # Write the content to the file
        with open(target_path, 'wb') as f:
            f.write(response.content)

        # Make the file executable
        os.chmod(target_path, 0o755)

        print(f"Successfully updated saltbox.fact to version {latest_version} at {target_path}")
    except requests.RequestException as e:
        print(f"Error downloading saltbox.fact: {e}")
    except IOError as e:
        print(f"Error writing saltbox.fact: {e}")
    except Exception as e:
        print(f"Unexpected error updating saltbox.fact: {e}")


def update_saltbox(saltbox_repo_path, saltbox_playbook_file, verbosity=0):
    print("Updating Saltbox...")

    if not os.path.isdir(saltbox_repo_path):
        print("Error: SB_REPO_PATH does not exist or is not a directory.")
        sys.exit(1)

    manage_ansible_venv(False)

    # Define custom commands and permission changes for Saltbox update
    custom_commands = [
        f"cp {saltbox_repo_path}/defaults/ansible.cfg.default {saltbox_repo_path}/ansible.cfg"
    ]

    # Check commit hash before update
    old_commit_hash = get_git_commit_hash(saltbox_repo_path)

    git_fetch_and_reset(saltbox_repo_path, "master", custom_commands=custom_commands)

    # Always update saltbox.fact during update
    download_and_install_saltbox_fact(always_update=False)

    # Run Settings role with specified tags and skip-tags
    tags = ['settings']
    skip_tags = ['sanity-check', 'pre-tasks']
    run_ansible_playbook(saltbox_repo_path, saltbox_playbook_file, ANSIBLE_PLAYBOOK_BINARY_PATH, tags, skip_tags,
                         verbosity)

    # Check commit hash after update
    new_commit_hash = get_git_commit_hash(saltbox_repo_path)

    if old_commit_hash != new_commit_hash:
        print("Saltbox Commit Hash changed, updating tags cache.")
        asyncio.run(run_and_cache_ansible_tags(saltbox_repo_path, saltbox_playbook_file, ""))

    print("Saltbox Update Completed.")


def update_sandbox(sandbox_repo_path, sandbox_playbook_file, verbosity=0):
    print("Updating Sandbox...")

    if not os.path.isdir(sandbox_repo_path):
        print(f"Error: {sandbox_repo_path} does not exist or is not a directory.")
        sys.exit(1)

    # Define custom commands for Sandbox update
    custom_commands = [
        f"cp {sandbox_repo_path}/defaults/ansible.cfg.default {sandbox_repo_path}/ansible.cfg"
    ]

    # Check commit hash before update
    old_commit_hash = get_git_commit_hash(sandbox_repo_path)

    git_fetch_and_reset(sandbox_repo_path, "master", custom_commands=custom_commands)

    # Run Settings role with specified tags and skip-tags
    tags = ['settings']
    skip_tags = ['sanity-check', 'pre-tasks']
    run_ansible_playbook(sandbox_repo_path, sandbox_playbook_file, ANSIBLE_PLAYBOOK_BINARY_PATH, tags, skip_tags,
                         verbosity)

    # Check commit hash after update
    new_commit_hash = get_git_commit_hash(sandbox_repo_path)

    if old_commit_hash != new_commit_hash:
        print("Sandbox Commit Hash changed, updating tags cache.")
        asyncio.run(run_and_cache_ansible_tags(sandbox_repo_path, sandbox_playbook_file, ""))

    print("Sandbox Update Completed.")


def update_sb(sb_repo_path):
    print("Updating sb.")

    if not os.path.isdir(sb_repo_path):
        print(f"Error: {sb_repo_path} does not exist or is not a directory.")
        sys.exit(1)

    # Perform git operations
    git_fetch_and_reset(sb_repo_path, "master")

    # Specific task for sb_update: Change permissions of sb.sh to 775
    sb_sh_path = os.path.join(sb_repo_path, 'sb.sh')
    if os.path.isfile(sb_sh_path):
        os.chmod(sb_sh_path, 0o775)
        print(f"Permissions changed for {sb_sh_path}.")
    else:
        print(f"Error: {sb_sh_path} does not exist or is not a file.")
        sys.exit(1)

    # Hardcoded paths
    release_file_path = os.path.join(sb_repo_path, 'release.txt')
    target_binary_path = os.path.join(sb_repo_path, 'sb')

    # Read the release.txt file to get the GitHub tag
    if not os.path.isfile(release_file_path):
        print(f"Error: {release_file_path} does not exist.")
        sys.exit(1)

    with open(release_file_path, 'r') as release_file:
        github_tag = release_file.readline().strip()

    # Extract the version number from the tag
    if not github_tag.startswith('refs/tags/'):
        print(f"Error: Invalid tag format in {release_file_path}.")
        sys.exit(1)

    version = github_tag[len('refs/tags/'):]
    if not version:
        print(f"Error: No version found in tag {github_tag}.")
        sys.exit(1)

    # Form the URL for the binary download
    download_url = f"https://github.com/saltyorg/sb/releases/download/{version}/sb"

    # Download the binary file
    response = requests.get(download_url)
    if response.status_code != 200:
        print(f"Error: Failed to download the binary from {download_url}.")
        sys.exit(1)

    # Save the downloaded binary to a temporary file
    temp_binary_path = target_binary_path + '.tmp'
    with open(temp_binary_path, 'wb') as temp_binary_file:
        temp_binary_file.write(response.content)

    # Check if the downloaded file is a binary
    mime = magic.Magic(mime=True)
    file_type = mime.from_file(temp_binary_path)
    if not file_type.startswith('application/'):
        print(f"Error: Downloaded file is not a binary. Detected type: {file_type}")
        os.remove(temp_binary_path)
        sys.exit(1)

    # Replace the old binary with the new one
    if os.path.isfile(temp_binary_path):
        os.replace(temp_binary_path, target_binary_path)
        print(f"Updated binary at {target_binary_path}.")

        # Ensure the new binary is executable
        os.chmod(target_binary_path, 0o755)
        print(f"Permissions changed for {target_binary_path} to be executable.")
    else:
        print(f"Error: Failed to write the new binary to {temp_binary_path}.")
        sys.exit(1)


def add_git_safe_directory_if_needed(directory):
    # Check if the directory is already marked as safe
    result = subprocess.run(['git', 'config', '--global', '--get-all', 'safe.directory'],
                            stdout=subprocess.PIPE,
                            text=True)
    safe_directories = result.stdout.strip().split('\n')

    if directory not in safe_directories:
        # Add the directory to safe.directory if it's not already marked as safe
        subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', directory])
        print(f"Added {directory} to git safe.directory.")


def check_and_update_repo(sb_repo_path):
    try:
        # Ensure the specified directory exists
        if not os.path.isdir(sb_repo_path):
            raise OSError(f"Directory does not exist: {sb_repo_path}")

        if os.path.isdir(SALTBOXMOD_REPO_PATH):
            add_git_safe_directory_if_needed(SALTBOXMOD_REPO_PATH)

        if os.path.isdir(SALTBOX_REPO_PATH):
            add_git_safe_directory_if_needed(SALTBOX_REPO_PATH)

        if os.path.isdir(SANDBOX_REPO_PATH):
            add_git_safe_directory_if_needed(SANDBOX_REPO_PATH)

        # Fetch latest changes from the remote without changing working directory
        subprocess.call(['git', 'fetch'], cwd=sb_repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Get the current HEAD hash and the upstream master hash without changing directory
        head_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=sb_repo_path).strip()
        upstream_hash = subprocess.check_output(['git', 'rev-parse', 'master@{upstream}'], cwd=sb_repo_path).strip()

        # Compare the hashes
        if head_hash != upstream_hash:
            print("sb is not up to date with origin. Updating.")

            # Update the repository
            update_sb(sb_repo_path)

            # Relaunching with previous arguments
            print("Relaunching with previous arguments.")
            executable_path = os.path.abspath(sys.argv[0])
            subprocess.call(['sudo', executable_path] + sys.argv[1:])
            sys.exit(0)

    except OSError as e:
        print(f"Error: {e}")
        sys.exit(1)


def handle_update(arguments):
    update_saltbox(SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, arguments.verbose)
    update_sandbox(SANDBOX_REPO_PATH, SANDBOX_PLAYBOOK_PATH, arguments.verbose)


def handle_install(arguments):
    saltbox_tags = []
    mod_tags = []
    sandbox_tags = []

    # Process each argument to split by comma, strip spaces, and filter out empty strings
    tags = [tag.strip() for arg in arguments.tags for tag in arg.split(',') if tag.strip()]
    skip_tags = [skip_tag.strip() for arg in arguments.skip_tags for skip_tag in arg.split(',') if skip_tag.strip()]

    # Check if sanity_check_use_cache is set
    ignore_cache = any(var.startswith("sanity_check_use_cache=") for var in arguments.extra_vars)

    # Function to check tag existence in a specific repo
    def check_tag_existence(repo_path, tag):
        cache = get_cached_tags(repo_path)
        return tag in cache.get("tags", [])

    # Separate tags based on their prefix
    for tag in tags:
        if tag.startswith("mod-"):
            mod_tags.append(tag[len("mod-"):])
        elif tag.startswith("sandbox-"):
            sandbox_tags.append(tag[len("sandbox-"):])
        else:
            saltbox_tags.append(tag)

    # Function to validate tags and suggest alternatives
    def validate_and_suggest(repo_path, provided_tags, prefix=""):
        if ignore_cache:
            return []
        cache_valid, missing_tags = check_cache(repo_path, provided_tags)
        suggestions = []
        for tag in missing_tags:
            if check_tag_existence(SANDBOX_REPO_PATH, tag):
                suggestions.append(f"'{prefix}{tag}' doesn't exist in Saltbox, but 'sandbox-{tag}' exists in Sandbox. "
                                   f"Use 'sandbox-{tag}' instead.")
            elif check_tag_existence(SALTBOX_REPO_PATH, tag):
                if prefix:
                    suggestions.append(f"'{prefix}{tag}' doesn't exist in Sandbox, but '{tag}' exists in Saltbox. "
                                       f"Remove the '{prefix}' prefix.")
            else:
                suggestions.append(f"'{prefix}{tag}' doesn't exist in Saltbox nor Sandbox. Use '-e "
                                   f"sanity_check_use_cache=false' if developing your own role.")
        return suggestions

    # Validate tags for Saltbox/Sandbox repositories
    all_suggestions = []

    if saltbox_tags:
        all_suggestions.extend(validate_and_suggest(SALTBOX_REPO_PATH, saltbox_tags))

    if sandbox_tags:
        all_suggestions.extend(validate_and_suggest(SANDBOX_REPO_PATH, sandbox_tags, "sandbox-"))

    cp = ColorPrinter()

    # If there are any suggestions, print them and exit
    if all_suggestions:
        print("----------------------------------------")

        cp.print_color('yellow', "The following issues were found with the provided tags:")
        for i, suggestion in enumerate(all_suggestions, 1):
            cp.print_color('red', f"{i}. {suggestion.split('.')[0]}.")
            cp.print_color('green', f"   Suggestion: {'.'.join(suggestion.split('.')[1:]).strip()}")

        sys.exit(1)

    # If all tags are valid, proceed with installation
    if saltbox_tags:
        run_ansible_playbook(SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, saltbox_tags,
                             skip_tags, arguments.verbose, arguments.extra_vars)

    if mod_tags:
        run_ansible_playbook(SALTBOXMOD_REPO_PATH, SALTBOXMOD_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, mod_tags,
                             skip_tags, arguments.verbose, arguments.extra_vars)

    if sandbox_tags:
        run_ansible_playbook(SANDBOX_REPO_PATH, SANDBOX_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, sandbox_tags,
                             skip_tags, arguments.verbose, arguments.extra_vars)

    if not (saltbox_tags or mod_tags or sandbox_tags):
        print("No valid tags were provided for installation.")
        sys.exit(1)


def handle_bench(_arguments):
    try:
        # Download and execute the bench.sh script
        subprocess.run("wget -qO- bench.sh | bash", shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while executing the benchmark: {e}")


def handle_diag(_arguments):
    # Run diag role
    tags = ['diag']
    run_ansible_playbook(SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, tags)


def handle_inventory(_arguments):
    file_path = "/srv/git/saltbox/inventories/host_vars/localhost.yml"
    default_editor = "nano"
    approved_editors = ["nano", "vim", "vi", "emacs", "gedit", "code"]

    # Check if file exists
    if not os.path.isfile(file_path):
        print("Error: The inventory file 'localhost.yml' does not yet exist.")
        return 1

    editor = os.getenv("EDITOR", default_editor)

    # Check if EDITOR is in the approved list
    is_approved = editor in approved_editors

    if not is_approved:
        if editor == default_editor:
            # Use default if EDITOR is not set or not approved
            subprocess.call([default_editor, file_path])
        else:
            # Prompt for confirmation if EDITOR is not in approved list
            print(f"The EDITOR variable is set to an unrecognized value: {editor}")
            confirm = input("Are you sure you want to use it to edit the file? (y/N) ").strip().lower()
            if confirm == "y":
                subprocess.call([editor, file_path])
            else:
                print(f"Using default editor: {default_editor}")
                subprocess.call([default_editor, file_path])
    else:
        subprocess.call([editor, file_path])


def handle_branch(arguments):
    print("Switching Saltbox repository branch...")
    custom_commands = [
        f"cp {SALTBOX_REPO_PATH}/defaults/ansible.cfg.default {SALTBOX_REPO_PATH}/ansible.cfg"
    ]

    git_fetch_and_reset(SALTBOX_REPO_PATH, arguments.branch_name, custom_commands=custom_commands)

    # Always update saltbox.fact during branch change
    download_and_install_saltbox_fact(always_update=False)

    # Run Settings role with specified tags and skip-tags
    tags = ['settings']
    skip_tags = ['sanity-check', 'pre-tasks']
    run_ansible_playbook(SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, tags, skip_tags,
                         arguments.verbose)

    print("Updating Saltbox tags cache.")
    asyncio.run(run_and_cache_ansible_tags(SALTBOX_REPO_PATH, SALTBOX_PLAYBOOK_PATH, ""))

    print(f"Saltbox repository branch switched to {arguments.branch_name} and settings updated.")


def handle_sandbox_branch(arguments):
    print("Switching Sandbox repository branch...")
    custom_commands = [
        f"cp {SANDBOX_REPO_PATH}/defaults/ansible.cfg.default {SANDBOX_REPO_PATH}/ansible.cfg"
    ]

    git_fetch_and_reset(SANDBOX_REPO_PATH, arguments.branch_name, custom_commands=custom_commands)

    # Run Settings role with specified tags and skip-tags
    tags = ['settings']
    skip_tags = ['sanity-check', 'pre-tasks']
    run_ansible_playbook(SANDBOX_REPO_PATH, SANDBOX_PLAYBOOK_PATH, ANSIBLE_PLAYBOOK_BINARY_PATH, tags, skip_tags,
                         arguments.verbose)

    print("Updating Sandbox tags cache.")
    asyncio.run(run_and_cache_ansible_tags(SANDBOX_REPO_PATH, SANDBOX_PLAYBOOK_PATH, ""))

    print(f"Sandbox repository branch switched to {arguments.branch_name} and settings updated.")


def handle_reinstall_fact(_arguments):
    print("Reinstalling saltbox.fact...")
    download_and_install_saltbox_fact(always_update=True)
    print("Reinstallation of saltbox.fact completed.")


def log_subprocess_result(result, cmd, log_file_path):
    """
    Logs the command, output, and errors of a subprocess result to a file, appending to the existing contents.

    Parameters:
    result (subprocess.CompletedProcess): The result object from subprocess.run.
    cmd (list): The command that was executed.
    log_file_path (str): Path to the log file where output and errors should be appended.
    """
    # Open the log file in append mode
    with open(log_file_path, "a") as log_file:
        # Log the command
        log_file.write(f"Command Executed: {' '.join(cmd)}\n")
        log_file.write(f"Return Code: {result.returncode}\n\n")

        # Decode the stdout and stderr
        stdout = result.stdout.decode('utf-8') if result.stdout else ""
        stderr = result.stderr.decode('utf-8') if result.stderr else ""

        # Write stdout to the log file if there is any output
        if stdout:
            log_file.write("Standard Output:\n")
            log_file.write(stdout + "\n\n")  # Add a newline for separation

        # Write stderr to the log file if there are any errors
        if stderr:
            log_file.write("Standard Error:\n")
            log_file.write(stderr + "\n\n")

        # Add a separator after each entry
        log_file.write("-" * 40 + "\n\n")


def run_command(cmd, env=None, cwd=None):
    """
    Executes a command using subprocess and logs the results, appending them to a log file.

    Parameters:
    cmd (list): The command to execute as a list of arguments.
    env (dict, optional): Dictionary of environment variables to set for the subprocess.
    cwd (str, optional): Directory to change to before executing the command.
    """
    # Define the log file path
    log_file_path = "/srv/git/saltbox/ansible-venv.log"

    # Run the command
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)

    # Log the result
    log_subprocess_result(result, cmd, log_file_path)

    if result.returncode != 0:
        raise Exception(f"Failed running {' '.join(cmd)} with error: {result.stderr.decode('utf-8')}")


def copy_files(paths, dest_dir):
    """
    Copies files from the given paths to the destination directory.
    
    Parameters:
    paths (list): A list of source file paths or glob patterns to match.
    dest_dir (str): The destination directory where files should be copied.
    """
    for path in paths:
        # Check if the path contains any glob pattern characters
        if any(char in path for char in "*?[]"):
            # Handle as a glob pattern
            files = glob.glob(path)
        else:
            # Handle as a direct path
            files = [path]

        for file_path in files:
            if os.path.isfile(file_path):
                shutil.copy(file_path, dest_dir)
            else:
                print(f"Warning: {file_path} is not a file and will not be copied.")


def manage_ansible_venv(recreate=False):
    if os.path.isdir("/srv/ansible/venv/bin") and not os.path.isfile("/srv/ansible/venv/bin/python3.12"):
        print("Python 3.12 not detected in venv, forcing recreate.")
        recreate = True

    if recreate:
        print("Recreating Ansible venv.")
    else:
        print("Updating Ansible venv.")

    ansible_venv_path = "/srv/ansible"
    cmd = ["lsb_release", "-cs"]
    release = subprocess.check_output(cmd, text=True).strip()

    # Remove the existing venv directory during recreate
    if recreate:
        cmd = ["rm", "-rf", ansible_venv_path]
        run_command(cmd)

    if not os.path.isdir(ansible_venv_path):
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        python_cmd = "python3.12"

        # Handle Python installation based on Ubuntu release
        if release == "focal" or release == "jammy":
            cmd = ["add-apt-repository", "ppa:deadsnakes/ppa", "--yes"]
            run_command(cmd, env)

            cmd = ["apt-get", "install", "python3.12", "python3.12-dev", "python3.12-distutils", "python3.12-venv",
                   "-y"]
            run_command(cmd, env)

            cmd = [python_cmd, "-m", "ensurepip"]
            run_command(cmd)

            os.makedirs(ansible_venv_path, exist_ok=True)
            cmd = [python_cmd, "-m", "venv", "venv"]
            run_command(cmd, cwd=ansible_venv_path)

        elif release == "noble":
            os.makedirs(ansible_venv_path, exist_ok=True)
            cmd = [python_cmd, "-m", "venv", "venv"]
            run_command(cmd, cwd=ansible_venv_path)

        else:
            print("Unsupported OS.")
            sys.exit(1)

    cmd = ["/srv/ansible/venv/bin/python3", "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
           "--upgrade", "pip", "setuptools", "wheel"]
    run_command(cmd)

    cmd = ["/srv/ansible/venv/bin/python3", "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
           "--upgrade", "--requirement", "/srv/git/sb/requirements-saltbox.txt"]
    run_command(cmd)

    copy_files(["/srv/ansible/venv/bin/ansible*", "/srv/ansible/venv/bin/certbot", "/srv/ansible/venv/bin/apprise"],
               "/usr/local/bin/")

    cmd = ["chown", "-R", f"{SALTBOX_USER}:{SALTBOX_USER}", ansible_venv_path]
    run_command(cmd)

    if recreate:
        print("Done recreating Ansible venv.")
    else:
        print("Done updating Ansible venv.")


def handle_version(_args=None):
    print(f"Application Version: {__version__}")


################################
# SB Repository Updater
################################

relaunch_as_root()
check_and_update_repo(SB_REPO_PATH)

################################
# Argument Parser
################################

# Create the top-level parser
parser = argparse.ArgumentParser(description='Command line interface example.')
subparsers = parser.add_subparsers(help='Sub-command help')


def add_extra_vars_argument(arg_parser):
    arg_parser.add_argument('-e', '--extra-vars', action='append', help='Extra variables', default=[])


def add_verbosity_argument(arg_parser):
    arg_parser.add_argument('-v', '--verbose', action='count', help='Ansible Verbosity', default=0)


# Create a parser for the "update" command
parser_update = subparsers.add_parser('update', help='Updates Saltbox and Sandbox')
add_verbosity_argument(parser_update)
parser_update.set_defaults(func=handle_update)

# Create a parser for the "list" command
parser_list = subparsers.add_parser('list', help='List Saltbox and Sandbox tags')
parser_list.set_defaults(func=handle_list)

# Create a parser for the "install" command
parser_install = subparsers.add_parser('install', help='Install <tag>')
# Expect a single string argument for tags
parser_install.add_argument('tags', nargs='+', help='Tags to install')
parser_install.add_argument('--skip-tags', nargs='+', help='Tags to skip, separated by commas', default='')
add_extra_vars_argument(parser_install)
add_verbosity_argument(parser_install)
parser_install.set_defaults(func=handle_install)

# Create a parser for the "bench" command
parser_bench = subparsers.add_parser('bench', help='Run bench.sh')
parser_bench.set_defaults(func=handle_bench)

# Create a parser for the "diag" command
parser_diag = subparsers.add_parser('diag', help='Run Saltbox diagnose for support')
parser_diag.set_defaults(func=handle_diag)

# Create a parser for the "recreate-venv" command
parser_recreate_venv = subparsers.add_parser('recreate-venv', help='Re-create the Ansible Python Virtual Environment')
parser_recreate_venv.set_defaults(func=handle_recreate_venv)

# Create a parser for the "reinstall-facts" command
parser_reinstall_facts = subparsers.add_parser('reinstall-facts', help='Reinstall the saltbox.fact file')
parser_reinstall_facts.set_defaults(func=handle_reinstall_fact)

# Create a parser for the "inventory" command
parser_inventory = subparsers.add_parser('inventory', help="Manage inventory 'localhost.yml' file")
parser_inventory.set_defaults(func=handle_inventory)

# Create a parser for the "branch" command
parser_branch = subparsers.add_parser('branch', help='Change the branch of the Saltbox repository.')
parser_branch.add_argument('branch_name', type=str,
                           help='The name of the branch to switch to in the Saltbox repository.')
parser_branch.set_defaults(func=handle_branch)
add_verbosity_argument(parser_branch)

# Create a parser for the "sandbox-branch" command
parser_sandbox_branch = subparsers.add_parser('sandbox-branch', help='Change the branch of the Sandbox repository.')
parser_sandbox_branch.add_argument('branch_name', type=str,
                                   help='The name of the branch to switch to in the Sandbox repository.')
parser_sandbox_branch.set_defaults(func=handle_sandbox_branch)
add_verbosity_argument(parser_sandbox_branch)

# Create a parser for the "version" command
parser_handle_version = subparsers.add_parser('version', help='Reports the version of the binary')
parser_handle_version.set_defaults(func=handle_version)

# Add the --version argument to the main parser
parser.add_argument('--version', action='store_true', help='Reports the version of the binary')

args = parser.parse_args()
# Call the appropriate handler function
if args.version:
    handle_version()
elif 'func' in args:
    args.func(args)
else:
    parser.print_help()
