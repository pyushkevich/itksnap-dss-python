# ITK-SNAP DSS Python Tools

Python tools for ITK-SNAP Distributed Segmentation Service (DSS), including a client for service providers and workspace manipulation utilities.

## Overview

This package provides two main components:

1. **DSSClient** - HTTP client for interacting with DSS middleware as a service provider
2. **WorkspaceWrapper** - Tools for programmatic manipulation of ITK-SNAP workspace files

The ITK-SNAP DSS enables medical image segmentation algorithms to be deployed as web services. Service providers claim tickets, download data, process it, and upload results back to the middleware.

For comprehensive DSS documentation, visit: https://alfabis-server.readthedocs.io/en/latest/

## DSS Architecture

The DSS system consists of three layers:

- **Client**: ITK-SNAP GUI or `itksnap-wt` command-line tools
- **Middleware**: Web application that orchestrates communication (e.g., https://dss.itksnap.org)
- **Service Providers**: Algorithm implementations that process tickets (use this library)

## Installation

```bash
pip install itksnap-dss
```

## Quick Start

### DSSClient - Service Provider Operations

```python
from itksnap_dss import DSSClient

# Connect and authenticate
client = DSSClient('https://dss.itksnap.org')
client.login()

# List services and claim a ticket
services = client.dssp_list_services()
service_hash = services['hash'].iloc[0]

ticket_df = client.dssp_claim_ticket(
    services=[service_hash],
    provider='my_provider',
    provider_code='instance_1'
)

if ticket_df is not None:
    ticket_id = ticket_df['ticket'].iloc[0]
    
    # Download input files
    client.dssp_download_ticket(ticket_id, f'/tmp/ticket_{ticket_id}')
    
    # Process data and update progress
    client.dssp_log(ticket_id, 'info', 'Processing started')
    client.dssp_set_progress(ticket_id, 0.5)
    
    # Upload results
    client.dssp_upload_ticket(ticket_id, 'result_workspace.itksnap')
    
    # Mark complete
    client.dssp_set_progress(ticket_id, 1.0)
    client.dssp_set_status(ticket_id, 'success')
```

### WorkspaceWrapper - Workspace Manipulation

```python
from itksnap_dss import WorkspaceWrapper

# Load and modify workspace
ws = WorkspaceWrapper('input.itksnap')

# Add/modify layers
ws.add_layer('OverlayRole', 'segmentation.nii.gz')
ws.set_layer_nickname('Layers.Layer[001]', 'My Segmentation')
ws.add_tag_to_layer('Layers.Layer[001]', 'result')

# Set labels
ws.set_labels('labels.txt')

# Export workspace with scrambled filenames
ws.export_workspace('output.itksnap', scramble_filenames=True)

# Save workspace
ws.save_workspace('modified.itksnap')
```

## Service Provider Workflow

1. **Authenticate** - Login to middleware server
2. **List Services** - Check registered services  
3. **Claim Ticket** - Get next processing job
4. **Download Files** - Retrieve input workspace and images
5. **Process Data** - Run algorithm, modify workspace
6. **Update Progress** - Keep users informed
7. **Upload Results** - Send result workspace back
8. **Mark Status** - Set as 'success' or 'failed'

## API Reference

### DSSClient - Provider Operations

#### Connection
- `DSSClient(server, verify=True)` - Initialize connection
- `login(token=None)` - Authenticate with token

#### Service & Ticket Management
- `dssp_list_services()` - List available services
- `dssp_claim_ticket(services, provider, provider_code)` - Claim next ticket
- `dssp_wait_for_ticket(..., timeout, interval)` - Wait for ticket with timeout
- `dssp_download_ticket(ticket, outdir)` - Download input files

#### Progress & Logging
- `dssp_set_progress(ticket, progress, chunk_start=0.0, chunk_end=1.0)` - Update progress
- `dssp_log(ticket, category, message)` - Log message (info/warning/error)
- `dssp_attach(ticket, desc, filename, mime_type='')` - Attach file to next log

#### Results & Status
- `dssp_upload_ticket(ticket, workspace_file, wsfile_suffix='')` - Upload result workspace
- `dssp_set_status(ticket, status)` - Mark as 'success' or 'failed'

### WorkspaceWrapper - Workspace Manipulation

#### File Operations
- `WorkspaceWrapper(workspace_file=None)` - Create wrapper
- `load_workspace(workspace_file)` - Load from file
- `save_workspace(workspace_file)` - Save to file
- `export_workspace(ws_file, scramble_filenames=False)` - Export with NIfTI conversion

#### Layer Management
- `get_number_of_layers()` - Count layers
- `find_layer_by_role(role, pos_in_role=0)` - Find layer by role
- `add_layer(role, filename)` - Add new layer
- `set_layer(role, filename)` - Set/replace layer
- `set_layer_nickname(layer_key, value)` - Set nickname
- `get_layer_actual_path(folder)` - Resolve layer path (handles moved workspaces)

#### Label Management
- `set_labels(label_file)` - Load and set label descriptions
- `load_color_label_file_to_registry(label_file, registry)` - Load labels to registry

#### Tag Management
- `get_tags(folder)` - Get tags from folder
- `put_tags(folder, tags)` - Set tags in folder
- `add_tag(folder, tag)` - Add single tag
- `remove_tag(folder, tag)` - Remove single tag
- `add_tag_to_layer(layer_key, tag)` - Add tag to layer
- `remove_tag_from_layer(layer_key, tag)` - Remove tag from layer

### Registry - Low-Level Configuration

The `Registry` class provides hierarchical key-value storage for workspace metadata:

- `entry(key)` - Access registry entry (use `.get()` / `.set()`)
- `folder(key)` - Access registry folder
- `has_entry(key)` / `has_folder(key)` - Check existence
- `read_from_xml_file(filename)` / `write_to_xml_file(filename)` - File I/O

## Example: Complete Service Provider

```python
#!/usr/bin/env python3
from itksnap_dss import DSSClient, WorkspaceWrapper
import os

def process_ticket(client, ticket_id, workdir):
    """Process a single ticket."""
    try:
        # Download input
        client.dssp_log(ticket_id, 'info', 'Downloading input files')
        client.dssp_download_ticket(ticket_id, workdir)
        
        # Find workspace file
        ws_file = next(f for f in os.listdir(workdir) if f.endswith('.itksnap'))
        ws_path = os.path.join(workdir, ws_file)
        
        # Load workspace and process
        ws = WorkspaceWrapper(ws_path)
        client.dssp_log(ticket_id, 'info', 'Processing started')
        client.dssp_set_progress(ticket_id, 0.3)
        
        # Your algorithm here - modify workspace, add layers, etc.
        # ws.add_layer('OverlayRole', 'result.nii.gz')
        # ws.set_labels('labels.txt')
        
        client.dssp_set_progress(ticket_id, 0.8)
        
        # Save and upload results
        result_path = os.path.join(workdir, 'result.itksnap')
        ws.save_workspace(result_path)
        
        client.dssp_log(ticket_id, 'info', 'Uploading results')
        client.dssp_upload_ticket(ticket_id, result_path)
        
        # Mark complete
        client.dssp_set_progress(ticket_id, 1.0)
        client.dssp_set_status(ticket_id, 'success')
        
    except Exception as e:
        client.dssp_log(ticket_id, 'error', f'Failed: {str(e)}')
        client.dssp_set_status(ticket_id, 'failed')

def main():
    client = DSSClient('http://localhost:8080')
    client.login()
    
    services = client.dssp_list_services()
    service_hash = services['hash'].iloc[0]
    
    print(f"Provider for: {services['service'].iloc[0]}")
    while True:
        ticket = client.dssp_wait_for_ticket(
            [service_hash], 'my_provider', 'instance_1', timeout=60
        )
        if ticket is not None:
            ticket_id = ticket['ticket'].iloc[0]
            process_ticket(client, ticket_id, f'/tmp/ticket_{ticket_id}')

if __name__ == '__main__':
    main()
```

## Command-Line Equivalents

Python methods corresponding to `itksnap-wt` provider commands:

| Command-Line | Python Method |
|-------------|---------------|
| `-dssp-services-list` | `dssp_list_services()` |
| `-dssp-services-claim` | `dssp_claim_ticket()` |
| `-dssp-tickets-download` | `dssp_download_ticket()` |
| `-dssp-tickets-set-progress` | `dssp_set_progress()` |
| `-dssp-tickets-log` | `dssp_log()` |
| `-dssp-tickets-attach` | `dssp_attach()` |
| `-dssp-tickets-upload` | `dssp_upload_ticket()` |
| `-dssp-tickets-success/-fail` | `dssp_set_status()` |

## License

See LICENSE file for details.

## References

- [DSS Documentation](https://alfabis-server.readthedocs.io/en/latest/)
- [ITK-SNAP](http://www.itksnap.org)
