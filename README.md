# Alfabis Python Client for ITK-SNAP DSS

A Python client library for interacting with the ITK-SNAP Distributed Segmentation Service (DSS) middleware as a service provider.

## Overview

The ITK-SNAP DSS (Distributed Segmentation Services) is an architecture that enables medical image segmentation algorithms to be deployed as web services. This Python client allows algorithm developers to create service providers that claim processing tickets, download input data, perform segmentation, and upload results back to the DSS middleware server.

For comprehensive DSS documentation, visit: https://alfabis-server.readthedocs.io/en/latest/

## DSS Architecture

The DSS system consists of three layers:

- **Client**: GUI (ITK-SNAP) or command-line tools (itksnap-wt) that submit processing requests
- **Middleware**: Web application (e.g., https://dss.itksnap.org) that orchestrates communication
- **Service Providers**: Algorithm implementations that process tickets (this library helps you build these)

## Installation

```bash
pip install itksnap-dss
```

## Quick Start

### 1. Connect and Authenticate

```python
from itksnap_dss import DSSClient

# Connect to DSS middleware server
client = DSSClient('https://dss.itksnap.org')

# Authenticate (you'll be prompted for a token from the server)
client.login()
```

### 2. List Available Services

```python
# See which services you're registered to provide
services = client.dssp_list_services()
print(services)
#              service version                                      hash provider
# 0        MRI-NeckCut   1.0.0  e0a316038e9cbe6a000e07c82758532a8863f51f     test
# 1  RegistrationExample   0.1.0  b7392368dc5dcec910bb8b87006ae38fd1f2cb32  testlab
```

### 3. Claim and Process a Ticket

```python
# Extract service hash from the services list
service_hash = services['hash'].iloc[0]

# Claim a ticket for this service
ticket_df = client.dssp_claim_ticket(
    services=[service_hash],
    provider='testlab',
    provider_code='instance_1'
)

if ticket_df is not None:
    ticket_id = ticket_df['ticket'].iloc[0]
    print(f"Claimed ticket {ticket_id}")
    
    # Download input files
    client.dssp_download_ticket(ticket_id, f'/tmp/ticket_{ticket_id}')
    
    # Process the data (your algorithm here)
    # ...
    
    # Update progress and log messages
    client.dssp_log(ticket_id, 'info', 'Processing started')
    client.dssp_set_progress(ticket_id, 0.5)  # 50% complete
    
    # Attach intermediate results
    client.dssp_attach(ticket_id, 'Quality metrics', 'metrics.txt', 'text/plain')
    client.dssp_log(ticket_id, 'info', 'Quality check passed')
    
    # Mark as complete
    client.dssp_set_progress(ticket_id, 1.0)
    client.dssp_set_status(ticket_id, 'success')
else:
    print("No tickets available")
```

### 4. Wait for Tickets (Daemon Mode)

```python
# Continuously wait for tickets with timeout
while True:
    ticket_df = client.dssp_wait_for_ticket(
        services=[service_hash],
        provider='testlab',
        provider_code='instance_1',
        timeout=300,  # Wait up to 5 minutes
        interval=15   # Check every 15 seconds
    )
    
    if ticket_df is not None:
        # Process ticket...
        pass
```

## Service Provider Workflow

A typical service provider follows this workflow:

1. **List Services** - Check which services you're registered for
2. **Claim Ticket** - Get the next available processing job
3. **Download Files** - Retrieve input data for the ticket
4. **Process Data** - Run your segmentation algorithm
5. **Update Progress** - Keep users informed during processing
6. **Log Messages** - Provide status updates, warnings, or errors
7. **Attach Files** - Upload intermediate results or quality metrics
8. **Upload Results** - Send processed data back to server (Note: upload method not yet implemented in this client)
9. **Mark Status** - Set ticket as 'success' or 'failed'

## API Reference

### Connection & Authentication

#### `DSSClient(server, verify=True)`
Initialize a connection to the DSS middleware server.

**Parameters:**
- `server` (str): Server URL (e.g., 'https://dss.itksnap.org')
- `verify` (bool): Verify SSL certificates (default: True)

#### `login(token=None)`
Authenticate with the server using a 40-character token.

**Equivalent CLI:** `itksnap-wt -dss-auth <server>`

### Service Management

#### `dssp_list_services()`
List all services you're registered as a provider for.

**Returns:** DataFrame with columns: service, version, hash, provider

**Equivalent CLI:** `itksnap-wt -dssp-services-list`

### Ticket Management

#### `dssp_claim_ticket(services, provider, provider_code)`
Claim the next available ticket for one or more services.

**Parameters:**
- `services` (List[str]): Service git hashes
- `provider` (str): Provider identifier
- `provider_code` (str): Unique instance identifier

**Returns:** DataFrame with ticket info, or None if no tickets available

**Equivalent CLI:** `itksnap-wt -dssp-services-claim <service_hash_list> <provider> <instance_id>`

#### `dssp_wait_for_ticket(services, provider, provider_code, timeout=300, interval=15)`
Wait for a ticket to become available.

**Equivalent CLI:** `itksnap-wt -dssp-services-claim <service_hash_list> <provider> <instance_id> <timeout>`

#### `dssp_download_ticket(ticket, outdir)`
Download all input files for a ticket to a directory.

**Equivalent CLI:** `itksnap-wt -dssp-tickets-download <id> <dir>`

### Progress & Logging

#### `dssp_set_progress(ticket, progress, chunk_start=0.0, chunk_end=1.0)`
Update processing progress (values in range [0, 1]).

**Equivalent CLI:** `itksnap-wt -dssp-tickets-set-progress <id> <start> <end> <value>`

#### `dssp_log(ticket, category, message)`
Add a log message (category: 'info', 'warning', or 'error').

**Equivalent CLI:** `itksnap-wt -dssp-tickets-log <id> <type> <msg>`

#### `dssp_attach(ticket, desc, filename, mime_type='')`
Attach a file to be linked with the next log message.

**Equivalent CLI:** `itksnap-wt -dssp-tickets-attach <id> <desc> <file> [mimetype]`

### Status Control

#### `dssp_set_status(ticket, status)`
Mark ticket as 'success' or 'failed'.

**Equivalent CLI:** 
- `itksnap-wt -dssp-tickets-success <id>`
- `itksnap-wt -dssp-tickets-fail <id> <msg>`

## Example: Complete Service Provider Script

```python
#!/usr/bin/env python3
"""
Example DSS service provider daemon that continuously processes tickets.
"""

from itksnap_dss import DSSClient
import time

def process_ticket(client, ticket_id, workdir):
    """Process a single ticket."""
    try:
        # Download input data
        client.dssp_log(ticket_id, 'info', 'Downloading input files')
        client.dssp_download_ticket(ticket_id, workdir)
        
        # Your processing algorithm here
        client.dssp_log(ticket_id, 'info', 'Starting processing')
        client.dssp_set_progress(ticket_id, 0.2)
        
        # ... run your algorithm ...
        time.sleep(5)  # Simulate processing
        
        client.dssp_set_progress(ticket_id, 0.8)
        client.dssp_log(ticket_id, 'info', 'Processing complete')
        
        # Upload results (not yet implemented in this client)
        # client.dssp_upload_ticket(ticket_id, result_workspace)
        
        # Mark as successful
        client.dssp_set_progress(ticket_id, 1.0)
        client.dssp_set_status(ticket_id, 'success')
        
    except Exception as e:
        # Handle errors
        client.dssp_log(ticket_id, 'error', f'Processing failed: {str(e)}')
        client.dssp_set_status(ticket_id, 'failed')

def main():
    # Initialize client
    client = DSSClient('http://localhost:8080')
    client.login()
    
    # Get service hash
    services = client.dssp_list_services()
    service_hash = services['hash'].iloc[0]
    
    # Main processing loop
    print(f"Starting service provider for {services['service'].iloc[0]}")
    while True:
        ticket_df = client.dssp_wait_for_ticket(
            services=[service_hash],
            provider='testlab',
            provider_code='instance_1',
            timeout=60
        )
        
        if ticket_df is not None:
            ticket_id = ticket_df['ticket'].iloc[0]
            print(f"Processing ticket {ticket_id}")
            process_ticket(client, ticket_id, f'/tmp/ticket_{ticket_id}')

if __name__ == '__main__':
    main()
```

## Command-Line Equivalents

This Python client provides equivalents to the `itksnap-wt` command-line tool's provider commands:

| Command-Line | Python Method |
|-------------|---------------|
| `-dssp-services-list` | `dssp_list_services()` |
| `-dssp-services-claim <hash> <provider> <instance>` | `dssp_claim_ticket(services, provider, provider_code)` |
| `-dssp-services-claim ... <timeout>` | `dssp_wait_for_ticket(..., timeout)` |
| `-dssp-tickets-download <id> <dir>` | `dssp_download_ticket(ticket, outdir)` |
| `-dssp-tickets-set-progress <id> <s> <e> <v>` | `dssp_set_progress(ticket, progress, chunk_start, chunk_end)` |
| `-dssp-tickets-log <id> <type> <msg>` | `dssp_log(ticket, category, message)` |
| `-dssp-tickets-attach <id> <desc> <file>` | `dssp_attach(ticket, desc, filename, mime_type)` |
| `-dssp-tickets-success <id>` | `dssp_set_status(ticket, 'success')` |
| `-dssp-tickets-fail <id> <msg>` | `dssp_set_status(ticket, 'failed')` + `dssp_log(..., 'error', msg)` |
| `-dssp-tickets-upload <id>` | *(Not yet implemented)* |
| `-dssp-tickets-status <id>` | *(Not yet implemented)* |

## Development Status

### Implemented Features
- ✅ Authentication and session management
- ✅ Service listing
- ✅ Ticket claiming (single and multi-service)
- ✅ Waiting for tickets with timeout
- ✅ File listing and downloading
- ✅ Progress updates
- ✅ Logging (info/warning/error)
- ✅ File attachments
- ✅ Status updates (success/failed)

### Not Yet Implemented
- ❌ Ticket result upload (`-dssp-tickets-upload`)
- ❌ Ticket status check (`-dssp-tickets-status`)

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please submit issues and pull requests on the project repository.

## References

- [DSS Documentation](https://alfabis-server.readthedocs.io/en/latest/)
- [DSS Service Developer's Guide](https://alfabis-server.readthedocs.io/en/latest/service_quick_start.html)
- [DSS REST API Reference](https://alfabis-server.readthedocs.io/en/latest/reference.html)
- [ITK-SNAP](http://www.itksnap.org)
