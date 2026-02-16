"""
DSSClient - Python client for ITK-SNAP Distributed Segmentation Service (DSS)

This module provides a Python client for interacting with the ITK-SNAP DSS middleware
server as a service provider. The DSS architecture enables medical image segmentation
algorithms to be deployed as web services accessible to clients through ITK-SNAP GUI
or command-line tools.

DSS Architecture:
    The DSS system consists of three layers:
    - Client: GUI (ITK-SNAP) or command-line tools (itksnap-wt)
    - Middleware: Web application orchestrating communication between clients and providers
    - Service Providers: Algorithm developers offering segmentation services

Provider Workflow:
    1. List available services for which you are registered as a provider
    2. Claim a ticket (processing job) for a service
    3. Download input files associated with the ticket
    4. Process the data
    5. Update ticket progress and log messages during processing
    6. Upload results back to the middleware server
    7. Mark ticket as success or failed

For more information, visit: https://alfabis-server.readthedocs.io/en/latest/
"""

import httpx
import pandas as pd
import keyring
import getpass
import time
import tempfile
from tqdm.auto import tqdm
from io import StringIO
from typing import List, Literal
import os

class DSSClient:
    """
    Client for interacting with ITK-SNAP DSS middleware server as a service provider.
    
    This class provides methods to authenticate with a DSS middleware server and perform
    all provider-level operations including claiming tickets, downloading input data,
    updating progress, logging messages, and uploading results.
    
    Attributes:
        server (str): The DSS middleware server URL (e.g., 'https://dss.itksnap.org')
        key (str): Keyring identifier for storing session credentials
        verify (bool): Whether to verify SSL certificates
        cli (httpx.Client): HTTP client with session cookies
    
    Example:
        >>> client = DSSClient('https://dss.itksnap.org')
        >>> client.login()  # Prompts for authentication token
        >>> services = client.dssp_list_services()
        >>> ticket = client.dssp_claim_ticket(['service_hash'], 'provider_code', 'instance_1')
    """

    def __init__(self, server:str, verify=True):
        self.server = server
        self.key = f'itksnap_dss_python:{server}'
        self.verify = verify

        sess_id = keyring.get_password("system", self.key)
        cookies = {'webpy_session_id': sess_id} if sess_id is not None else None
        self.cli = httpx.Client(verify=False, cookies=cookies)

    def get_(self, loc, **kwargs):
        r = self.cli.get(f'{self.server}/{loc}', **kwargs)
        r.raise_for_status()
        return r

    def post_(self, loc, **kwargs):
        r = self.cli.post(f'{self.server}/{loc}', **kwargs)
        r.raise_for_status()
        return r

    def csv_(self, r, names):
        return pd.read_csv(StringIO(r.text), header=None, names=names)

    def login(self, token=None):
        """
        Authenticate with the DSS middleware server.
        
        Authenticates using a 40-character token obtained from the server's /token endpoint.
        Upon successful login, the session ID is stored in the system keychain for future use.
        
        Args:
            token (str, optional): Authentication token. If None, prompts user to visit
                the server's /token page and enter the token manually.
        
        Returns:
            httpx.Response: The server response containing session cookies
        
        Raises:
            httpx.HTTPStatusError: If authentication fails
        
        Example:
            >>> client = DSSClient('http://localhost:8080')
            >>> client.login()  # Interactive prompt
            Visit http://localhost:8080/token to obtain a token
            Enter the token: e851fa1804f4f9256fb937d904e420ed56e98d89d3ccd618
            Login successful, session id stored in keychain...
        
        Note:
            Corresponds to command-line: itksnap-wt -dss-auth <server>
        """
        if token is None:
            print(f'Visit {self.server}/token to obtain a token')
            token = getpass.getpass(prompt='Enter the token: ')
        
        r = self.post_('api/login', data={"token": token})
        sess_id = r.cookies.get('webpy_session_id')
        if sess_id is not None:
            keyring.set_password("system", self.key, sess_id)
            self.cli = httpx.Client(verify=False, cookies=r.cookies)
            print(f'Login successful, session id stored in keychain "system", key "{self.key}"')
        return r

    def dssp_list_services(self):
        """
        List all services for which you are registered as a provider.
        
        Retrieves the list of services that the authenticated user can provide.
        Each service is identified by its name, version, git hash, and provider code.
        
        Returns:
            pandas.DataFrame: DataFrame with columns:
                - service (str): Service name
                - version (str): Service version (semantic versioning)
                - hash (str): 40-character git commit hash identifying the service
                - provider (str): Provider code
        
        Example:
            >>> services = client.dssp_list_services()
            >>> print(services)
                        service version                                      hash provider
            0      MRI-NeckCut   1.0.0  e0a316038e9cbe6a000e07c82758532a8863f51f     test
            1  RegistrationExample   0.1.0  b7392368dc5dcec910bb8b87006ae38fd1f2cb32  testlab
        
        Note:
            Corresponds to command-line: itksnap-wt -dssp-services-list
        """
        r = self.get_('api/pro/services')
        return self.csv_(r, names=['service','version','hash','provider'])

    def dssp_claim_ticket(self, services: List[str], provider: str, provider_code: str):
        """
        Claim the next available ticket for one or more services.
        
        Attempts to claim a ticket (processing job) from the queue for the specified service(s).
        When a ticket is claimed, it becomes unavailable to other provider instances and must
        be processed immediately. Returns None if no tickets are available.
        
        Args:
            services (List[str]): List of service git hashes (40-character commit hashes).
                If multiple hashes are provided, returns the highest-priority ticket
                across all specified services.
            provider (str): Provider identifier code (e.g., 'testlab')
            provider_code (str): Unique instance identifier within the provider (e.g., 'instance_1').
                Used when running multiple parallel provider instances.
        
        Returns:
            pandas.DataFrame or None: DataFrame with columns if a ticket is available:
                - ticket (int): Ticket ID
                - service (str): Service hash the ticket belongs to
                - status (str): Ticket status (typically 'claimed')
            Returns None if no tickets are available.
        
        Example:
            >>> # Claim ticket for a single service
            >>> ticket = client.dssp_claim_ticket(['b7392368dc5dcec910bb8b87006ae38fd1f2cb32'], 
            ...                                    'testlab', 'instance_1')
            >>> if ticket is not None:
            ...     ticket_id = ticket['ticket'].iloc[0]
            ...     print(f"Claimed ticket {ticket_id}")
            
            >>> # Claim ticket for multiple services
            >>> ticket = client.dssp_claim_ticket(['hash1', 'hash2'], 'testlab', 'instance_1')
            >>> if ticket is not None:
            ...     service_hash = ticket['service'].iloc[0]  # Which service this ticket is for
        
        Note:
            Corresponds to command-line: itksnap-wt -dssp-services-claim <service_hash_list> <provider> <instance_id>
        """
        r = self.post_('api/pro/services/claims', data={'services': ','.join(services), 'provider':provider, 'code':provider_code})
        return self.csv_(r, names=['ticket','service','status']) if r.text != 'None' else None
    
    def dssp_wait_for_ticket(self, services: List[str], provider: str, provider_code: str, timeout:int=300, interval:int=15):
        """
        Wait for a ticket to become available, with timeout.
        
        Repeatedly attempts to claim a ticket at regular intervals until one becomes available
        or the timeout is reached. Displays a progress bar showing elapsed time.
        
        Args:
            services (List[str]): List of service git hashes
            provider (str): Provider identifier code
            provider_code (str): Unique instance identifier
            timeout (int, optional): Maximum time to wait in seconds. Defaults to 300 (5 minutes).
            interval (int, optional): Time between claim attempts in seconds. Defaults to 15.
        
        Returns:
            pandas.DataFrame or None: Ticket information if successfully claimed, None if timeout reached
        
        Example:
            >>> # Wait up to 10 minutes for a ticket
            >>> ticket = client.dssp_wait_for_ticket(['service_hash'], 'testlab', 'instance_1', 
            ...                                       timeout=600, interval=20)
            >>> if ticket is not None:
            ...     print("Ticket claimed!")
            ... else:
            ...     print("Timeout - no tickets available")
        
        Note:
            Corresponds to command-line: itksnap-wt -dssp-services-claim <service_hash> <provider> <instance_id> <timeout>
        """
        t_start = time.time()
        t_last_upd = t_start
        with tqdm(total=timeout) as pbar:
            while True:
                df = self.dssp_claim_ticket(services, provider, provider_code)
                if df is not None:
                    return df
                if time.time() - t_start >= timeout:
                    break
                time.sleep(interval)
                pbar.update(int(time.time() - t_last_upd))
                t_last_upd = time.time()
        return None

    def dssp_list_ticket_files(self, ticket:int):
        """
        List all input files associated with a ticket.
        
        Retrieves the list of files available for download for the specified ticket,
        including the workspace file and all image layers.
        
        Args:
            ticket (int): Ticket ID
        
        Returns:
            pandas.DataFrame: DataFrame with columns:
                - index (int): File index for downloading
                - filename (str): Original filename (anonymized)
        
        Example:
            >>> files = client.dssp_list_ticket_files(1)
            >>> print(files)
               index                                          filename
            0      0  layer_000_73f86306f91fdcac7a84159b3a916e21.nii.gz
            1      1  layer_001_a8533a499615e024637587466b574689.nii.gz
            2      2                     ticket_00000001.itksnap
        
        Note:
            This is a helper method used internally by dssp_download_ticket()
        """
        r = self.get_(f'api/pro/tickets/{ticket}/files/input')
        return self.csv_(r, names=['index','filename'])

    def dssp_download_ticket(self, ticket:int, outdir:str):
        """
        Download all input files for a claimed ticket.
        
        Downloads the ITK-SNAP workspace and all associated image files for the specified ticket.
        Files are saved to the output directory with anonymized filenames. A progress bar shows
        download progress.
        
        Args:
            ticket (int): Ticket ID to download
            outdir (str): Directory path where files will be saved. Created if it doesn't exist.
        
        Raises:
            httpx.HTTPStatusError: If download fails or ticket doesn't exist
        
        Example:
            >>> client.dssp_download_ticket(1, '/tmp/ticket_1')
            >>> # Files now in /tmp/ticket_1/:
            >>> #   ticket_00000001.itksnap
            >>> #   layer_000_73f86306f91fdcac7a84159b3a916e21.nii.gz
            >>> #   layer_001_a8533a499615e024637587466b574689.nii.gz
            >>> #   ...
        
        Note:
            - File names are anonymized (replaced with hashes) as part of the DSS privacy model
            - Use itksnap-wt workspace commands to extract layers by tag name
            - Corresponds to command-line: itksnap-wt -dssp-tickets-download <id> <dir>
        """
        df_files = self.dssp_list_ticket_files(ticket)
        os.makedirs(outdir, exist_ok=True)
        with tqdm(total=df_files.shape[0]) as pbar:
            for i, row in df_files.iterrows():
                r = self.get_(f'api/pro/tickets/{ticket}/files/input/{row["index"]}')
                with open(os.path.join(outdir, row["filename"]), 'wb') as f:
                    f.write(r.content)
                    pbar.update()

    def dssp_set_progress(self, ticket:int, progress:float, chunk_start:float=0.0, chunk_end:float=1.0):
        """
        Update the processing progress for a ticket.
        
        Sets the progress indicator visible to users in the ITK-SNAP interface. Progress can
        be specified for the entire job or for a specific chunk/phase of processing.
        
        Args:
            ticket (int): Ticket ID
            progress (float): Progress value within the chunk, in range [0, 1]
            chunk_start (float, optional): Start of the current processing chunk, in range [0, 1].
                Defaults to 0.0.
            chunk_end (float, optional): End of the current processing chunk, in range [0, 1].
                Defaults to 1.0.
        
        Raises:
            httpx.HTTPStatusError: If update fails
        
        Example:
            >>> # Simple progress update (40% complete overall)
            >>> client.dssp_set_progress(1, 0.4)
            
            >>> # Progress within a chunk (e.g., affine registration is 40% of total job)
            >>> # Now 50% done with affine registration = 20% overall
            >>> client.dssp_set_progress(1, progress=0.5, chunk_start=0.0, chunk_end=0.4)
            
            >>> # Progress in deformable registration (40-80% of total job)
            >>> client.dssp_set_progress(1, progress=0.5, chunk_start=0.4, chunk_end=0.8)
        
        Note:
            Corresponds to command-line: itksnap-wt -dssp-tickets-set-progress <id> <start> <end> <value>
        """
        self.post_(f'api/pro/tickets/{ticket}/progress', 
                data={'progress': progress, 'chunk_start':  chunk_start, 'chunk_end': chunk_end})

    def dssp_log(self, ticket: str, category: Literal['info','warning','error'], message: str):
        """
        Add a log message for a ticket.
        
        Sends a log message that will be visible to users in the ITK-SNAP DSS interface.
        Use this to provide status updates, warnings, or error information during processing.
        
        Args:
            ticket (str): Ticket ID
            category (Literal['info','warning','error']): Message severity level:
                - 'info': Informational message (e.g., "Registration completed successfully")
                - 'warning': Warning message (e.g., "Low image quality detected")
                - 'error': Error message (e.g., "Unable to detect anatomical landmarks")
            message (str): The log message text
        
        Raises:
            httpx.HTTPStatusError: If logging fails
        
        Example:
            >>> client.dssp_log(1, 'info', 'Ticket successfully downloaded')
            >>> client.dssp_log(1, 'info', 'Affine registration successful')
            >>> client.dssp_log(1, 'warning', 'Image resolution lower than recommended')
            >>> client.dssp_log(1, 'error', 'Failed to converge during optimization')
        
        Note:
            - Log messages appear in chronological order in the ITK-SNAP interface
            - Attachments added via dssp_attach() are linked to the next log message
            - Corresponds to command-line: itksnap-wt -dssp-tickets-log <id> <type> <msg>
        """
        self.post_(f'api/pro/tickets/{ticket}/{category}', data={'message': message})

    def dssp_set_status(self, ticket: str, status: Literal['failed','success']):
        """
        Mark a ticket as successfully completed or failed.
        
        Sets the final status of a ticket. Once marked as 'success', the results become
        available for download by the user. Once marked as 'failed', the ticket is closed
        and the user is notified.
        
        Args:
            ticket (str): Ticket ID
            status (Literal['failed','success']): Final ticket status:
                - 'success': Processing completed successfully, results ready
                - 'failed': Processing failed, ticket closed
        
        Raises:
            httpx.HTTPStatusError: If status update fails
        
        Example:
            >>> # Mark as successful (after uploading results)
            >>> client.dssp_set_progress(1, 1.0)  # Set 100% progress
            >>> client.dssp_set_status(1, 'success')
            
            >>> # Mark as failed
            >>> client.dssp_log(1, 'error', 'Registration failed to converge')
            >>> client.dssp_set_status(1, 'failed')
        
        Note:
            - Should be called after dssp_tickets_upload() for successful tickets
            - Corresponds to command-line: 
                itksnap-wt -dssp-tickets-success <id>
                itksnap-wt -dssp-tickets-fail <id> <msg>
        
        See Also:
            Use dssp_log() with category='error' to provide failure details before
            calling dssp_set_status(ticket, 'failed')
        """
        self.post_(f'api/pro/tickets/{ticket}/status', data={'status': status})

    def dssp_attach(self, ticket:str, desc: str, filename: str, mime_type:str = ''):
        """
        Attach a file to a ticket's log.
        
        Uploads a file (e.g., transformation matrix, quality metrics, debug output) that will
        be linked to the next log message issued for this ticket. Users can view/download
        attachments from the ITK-SNAP interface.
        
        Args:
            ticket (str): Ticket ID
            desc (str): Description of the attachment (shown to user)
            filename (str): Path to the file to attach
            mime_type (str, optional): MIME type of the file (e.g., 'text/plain', 'image/png').
                If empty, server will attempt to detect automatically.
        
        Returns:
            httpx.Response: Server response
        
        Raises:
            httpx.HTTPStatusError: If upload fails
            FileNotFoundError: If the specified file doesn't exist
        
        Example:
            >>> # Attach an affine transformation matrix
            >>> client.dssp_attach(1, 'Affine matrix', '/tmp/affine.mat', 'text/plain')
            >>> client.dssp_log(1, 'info', 'Affine registration successful')
            
            >>> # Attach registration output log
            >>> client.dssp_attach(1, 'Registration output', '/tmp/reg_output.txt', 'text/plain')
            >>> client.dssp_log(1, 'info', 'Deformable registration completed')
            
            >>> # Attach quality control image
            >>> client.dssp_attach(1, 'QC visualization', '/tmp/qc.png', 'image/png')
            >>> client.dssp_log(1, 'info', 'Quality control check passed')
        
        Note:
            - Attachments are linked to the NEXT log message, so call dssp_attach() before dssp_log()
            - Users can click a paperclip icon in ITK-SNAP to view/download attachments
            - Corresponds to command-line: itksnap-wt -dssp-tickets-attach <id> <desc> <file> [mimetype]
        """
        d = {"filename": os.path.basename(filename), "submit": "send", "desc": desc}
        if len(mime_type) > 0:
            d["mime_type"] = mime_type
        with open(filename, 'rb') as f:
            r = self.post_(f'api/pro/tickets/{ticket}/attachments', 
                           files={"myfile": f}, data=d)
            return r
    
    def dssp_upload_ticket(self, ticket: int, workspace_file: str, wsfile_suffix: str = ""):
        """
        Upload a workspace file and all its layer images to the server for a ticket.
        
        This method exports the workspace to a temporary directory (converting all layer
        images to NIfTI format with MD5-hashed filenames), then uploads all files to the
        server's input area for the specified ticket.
        
        Args:
            ticket (int): Ticket ID to upload files for
            workspace_file (str): Path to the ITK-SNAP workspace (.itksnap) file
            wsfile_suffix (str, optional): Optional suffix to add to workspace filename
                on the server (e.g., "_result" -> "ticket_00000123_result.itksnap")
        
        Returns:
            None
        
        Raises:
            httpx.HTTPStatusError: If any file upload fails
            FileNotFoundError: If the workspace file doesn't exist
            RuntimeError: If workspace export fails
        
        Example:
            >>> # Upload results workspace after processing
            >>> client.dssp_upload_ticket(123, '/tmp/result_workspace.itksnap')
            Exported workspace to /tmp/alfabis_xyz/ticket_00000123.itksnap
            Uploaded ticket_00000123.itksnap (0.1 MB)
            Uploaded layer_000_a3b5c7d9e1f2...nii.gz (45.2 MB)
            Uploaded layer_001_f8e3d1c4b2a6...nii.gz (38.7 MB)
            
            >>> # Upload with custom suffix
            >>> client.dssp_upload_ticket(123, 'output.itksnap', '_results')
            Exported workspace to /tmp/alfabis_xyz/ticket_00000123_results.itksnap
            ...
        
        Note:
            - All layer images are converted to compressed NIfTI (.nii.gz) format
            - Layer filenames are scrambled using MD5 hash for anonymization
            - Temporary files are automatically cleaned up after upload
            - Large files may take considerable time to upload
            - Corresponds to C++ WorkspaceAPI::UploadWorkspace()
        """
        # Import here to avoid circular dependency
        from .itksnap_ws import WorkspaceWrapper
        
        # Load the workspace
        ws = WorkspaceWrapper(workspace_file)
        
        # Create temporary directory for export
        # NOTE: C++ uses GetTempDirName() which creates platform-specific temp directory
        with tempfile.TemporaryDirectory(prefix='alfabis_') as tempdir:
            # Export the workspace file to the temporary directory
            # NOTE: Filename format matches C++ sprintf: "ticket_%08d%s.itksnap"
            ws_filename = f"ticket_{ticket:08d}{wsfile_suffix}.itksnap"
            ws_filepath = os.path.join(tempdir, ws_filename)
            
            # Export workspace with all layers to temp directory
            # NOTE: scramble_filenames=True uses MD5 hash like C++ GetNativeImageMD5Hash()
            ws.export_workspace(ws_filepath, scramble_filenames=True)
            
            print(f"Exported workspace to {ws_filepath}")
            
            # Collect all files in the directory to upload
            # NOTE: C++ uses Directory::Load() to enumerate files
            fn_to_upload = []
            for filename in os.listdir(tempdir):
                filepath = os.path.join(tempdir, filename)
                if os.path.isfile(filepath):
                    fn_to_upload.append(filepath)
            
            # Upload each file to the server
            # NOTE: C++ uses RESTClient::UploadFile with URL format "api/tickets/%d/files/input"
            # and form fields: myfile (file), filename (string), submit (string)
            with tqdm(total=len(fn_to_upload), desc="Uploading files") as pbar:
                for fn in fn_to_upload:
                    fn_name = os.path.basename(fn)
                    
                    # Prepare multipart form data matching C++ curl_formadd structure
                    data = {
                        'filename': fn_name,
                        'submit': 'send'
                    }
                    
                    with open(fn, 'rb') as f:
                        files = {
                            'myfile': (fn_name, f, 'application/octet-stream')
                        }
                        
                        # Make the upload request
                        # NOTE: Using 'api/pro' prefix for provider API instead of 'api'
                        r = self.post_(f'api/pro/tickets/{ticket}/files/input', 
                                      files=files, data=data)
                    
                    # Report upload statistics
                    file_size_mb = os.path.getsize(fn) / 1.0e6
                    pbar.set_postfix_str(f"{fn_name} ({file_size_mb:.1f} MB)")
                    pbar.update(1)