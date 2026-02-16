import SimpleITK as sitk
import os
import re
import shutil
import hashlib
from typing import List, Set
from copy import deepcopy
from .registry import Registry

class WorkspaceWrapper:
    """Wrapper for ITK-SNAP workspace files."""
    
    def __init__(self, workspace_file: str | None = None):
        self.registry = Registry()
        self.workspace_file_path = ""
        self.workspace_file_dir = ""
        self.workspace_saved_dir = ""
        self.moved = False
        if workspace_file:
            self.load_workspace(workspace_file)
    
    def load_workspace(self, workspace_file: str):
        """Load workspace from file."""
        self.registry.read_from_xml_file(workspace_file)
        self.workspace_file_path = os.path.abspath(workspace_file)
        self.workspace_file_dir = os.path.dirname(self.workspace_file_path)
        
        # Read the location where the file was saved initially
        self.workspace_saved_dir = self.registry.entry("SaveLocation").get("")
        
        # If the locations are different, we will attempt to find relative paths first
        self.moved = (self.workspace_file_dir != self.workspace_saved_dir)
    
    def save_workspace(self, workspace_file: str):
        """Save workspace to file."""
        self.workspace_file_path = os.path.abspath(workspace_file)
        self.workspace_file_dir = os.path.dirname(self.workspace_file_path)
        self.registry.entry("SaveLocation").set(self.workspace_file_dir)
        
        # Update all the paths before saving
        self.set_all_layer_paths_to_actual_paths()
        
        self.registry.write_to_xml_file(workspace_file)
        
        # Update internal values
        self.moved = False
        self.workspace_saved_dir = self.workspace_file_dir
    
    def get_number_of_layers(self) -> int:
        """Count layers by checking for Layers.Layer[%03d] keys in registry."""
        n_layers = 0
        while self.registry.has_folder(f"Layers.Layer[{n_layers:03d}]"):
            n_layers += 1
        return n_layers
    
    def find_layer_by_role(self, role: str, pos_in_role: int = 0) -> str:
        """Find layer key by role. Returns empty string if not found."""
        n_layers = self.get_number_of_layers()
        start, end, step = (0, n_layers, 1) if pos_in_role >= 0 else (n_layers - 1, -1, -1)
        role_count = 0 if pos_in_role >= 0 else 1
        
        for i in range(start, end, step):
            key = f"Layers.Layer[{i:03d}]"
            if not self.registry.has_folder(key):
                continue
            
            layer_folder = self.registry.folder(key)
            l_role = layer_folder.entry("Role").get("")
            
            if (l_role == role or 
                (role == "AnatomicalRole" and l_role in ("MainRole", "OverlayRole")) or
                (role == "AnyRole")):
                if role_count == abs(pos_in_role):
                    return key
                role_count += 1
        
        return ""
        
    def add_layer(self, role: str, filename: str) -> str:
        """Add layer to workspace. Returns layer key."""
        # Validity checks
        if role == "MainRole" and self.find_layer_by_role(role, 0):
            raise ValueError(f"A workspace cannot have more than one image in the {role} role")
        
        # Interpret anatomical role
        if role == "AnatomicalRole":
            role = "OverlayRole" if self.find_layer_by_role("MainRole", 0) else "MainRole"
        
        # May not add anything until main image exists
        if role != "MainRole" and not self.find_layer_by_role("MainRole", 0):
            raise ValueError(f"Cannot add image in {role} role to a workspace without main image")
        
        # Create layer key
        key = f"Layers.Layer[{self.get_number_of_layers():03d}]"
        
        # Create folder and add entries
        folder = self.registry.folder(key)
        folder.entry("AbsolutePath").set(os.path.abspath(filename))
        folder.entry("Role").set(role)
        
        # Update main layer dimensions if needed
        if role == "MainRole":
            self._update_main_layer_fields(key)
        
        return key
    
    def _update_main_layer_fields(self, layer_key: str):
        """Read image dimensions and store in ProjectMetaData."""
        layer_folder = self.registry.folder(layer_key)
        filename = layer_folder.entry("AbsolutePath").get("")
        
        # Read image header to get dimensions
        img = sitk.ReadImage(filename)
        dims = list(img.GetSize())
        
        # Store dimensions in registry
        layer_folder.folder("ProjectMetaData").folder("Files").folder("Grey").entry("Dimensions").set(dims)
    
    def get_layer_actual_path(self, folder: Registry|str) -> str:
        """
        Find a physical file corresponding to a file referenced by the workspace,
        accounting for the possibility that the workspace may have been moved or copied.
        """
        # Get the filename for the layer
        if isinstance(folder, str):
            folder = self.registry.folder(folder)
            
        layer_file_full = folder.entry("AbsolutePath").get("")
        
        # If the workspace has moved, try finding a relative location
        if self.moved and self.workspace_saved_dir:
            relative_path = ""
            
            # Test the simple thing: is the saved location included in the file path
            if layer_file_full.startswith(self.workspace_saved_dir):
                # Get the balance of the path
                relative_path = layer_file_full[len(self.workspace_saved_dir):]
                
                # Strip the leading slashes
                relative_path = relative_path.lstrip(os.sep)
            else:
                # Fallback: use relative path mechanism
                relative_path = os.path.relpath(layer_file_full, self.workspace_saved_dir)
            
            # Construct the moved file path
            moved_file_full = os.path.abspath(os.path.join(self.workspace_file_dir, relative_path))
            
            # If this file exists, use it
            if os.path.isfile(moved_file_full):
                layer_file_full = moved_file_full
        
        # Return the file - no guarantee that it exists...
        return layer_file_full
    
    def set_all_layer_paths_to_actual_paths(self):
        """Convert all layer paths in the workspace to actual paths."""
        for i in range(self.get_number_of_layers()):
            folder = self.get_layer_folder(i)
            actual_path = self.get_layer_actual_path(folder)
            folder.entry("AbsolutePath").set(actual_path)
    
    def get_number_of_mesh_layers(self) -> int:
        """Count mesh layers by checking for MeshLayers.Layer[%03d] keys."""
        n_layers = 0
        while self.registry.has_folder(f"MeshLayers.Layer[{n_layers:03d}]"):
            n_layers += 1
        return n_layers
    
    def get_layer_folder(self, layer_index: int) -> Registry:
        """Get the folder for the n-th layer."""
        key = f"Layers.Layer[{layer_index:03d}]"
        return self.registry.folder(key)
    
    def get_mesh_layer_folder(self, layer_index: int) -> Registry:
        """Get the folder for the n-th mesh layer."""
        key = f"MeshLayers.Layer[{layer_index:03d}]"
        if not self.registry.has_folder(key):
            raise ValueError(f"Mesh layer {layer_index} does not exist")
        return self.registry.folder(key)
    
    def get_layer_folder_by_key(self, layer_key: str) -> Registry:
        """Get layer folder by key."""
        if not layer_key or not self.registry.has_folder(layer_key):
            raise ValueError(f"Layer key {layer_key} does not exist")
        return self.registry.folder(layer_key)
    
    def is_key_valid_layer(self, key: str) -> bool:
        """Check if the provided key specifies a valid layer."""
        if not re.match(r"Layers\.Layer\[\d+\]", key):
            return False
        if not self.registry.has_folder(key):
            return False
        folder = self.registry.folder(key)
        return folder.has_entry("AbsolutePath") and folder.has_entry("Role")
    
    def is_key_valid_mesh_layer(self, key: str) -> bool:
        """Check if the provided key specifies a valid mesh layer."""
        if not re.match(r"MeshLayers\.Layer\[\d+\]", key):
            return False
        if not self.registry.has_folder(key):
            return False
        mesh_layer = self.registry.folder(key)
        if not mesh_layer.has_folder("MeshTimePoints"):
            return False
        tp_meshes = mesh_layer.folder("MeshTimePoints")
        tp_list = tp_meshes.find_folders_from_pattern(r"TimePoint\[\d+\]")
        if not tp_list:
            return False
        for tp_key in tp_list:
            tp_folder = tp_meshes.folder(tp_key)
            if not tp_folder.find_folders_from_pattern(r"PolyData\[\d+\]"):
                return False
        return True
    
    def set_layer(self, role: str, filename: str) -> str:
        """Assign an image layer to a specific role (main/seg)."""
        key = self.find_layer_by_role(role, 0)
        
        # If this role does not already exist, use add functionality
        if not key:
            return self.add_layer(role, filename)
        
        # Otherwise, clear the old folder and reassign
        folder = self.registry.folder(key)
        folder.clear()
        
        folder.entry("AbsolutePath").set(os.path.abspath(filename))
        folder.entry("Role").set(role)
        
        if role == "MainRole":
            self._update_main_layer_fields(key)
        
        return key
    
    def add_mesh_layer(self, filename: str, tp: int = 1) -> str:
        """Add a standalone mesh layer to the workspace."""
        # Main image has to be loaded already
        if not self.find_layer_by_role("MainRole", 0):
            raise ValueError("Cannot add mesh layer to workspace without main image")
        
        if tp < 1:
            raise ValueError("Time point must be >= 1")
        
        # Append a mesh layer folder
        key = f"MeshLayers.Layer[{self.get_number_of_mesh_layers():03d}]"
        
        # Create folder for this key
        mesh_layer = self.registry.folder(key)
        mesh_layer.entry("MeshType").set("StandaloneMesh")
        mesh_layer.entry("Nickname").set("")
        mesh_layer.entry("Tags").set("")
        
        # Create mesh time points
        tp_mesh = mesh_layer.folder("MeshTimePoints")
        new_tp = tp_mesh.folder(f"TimePoint[{tp:03d}]")
        new_tp.entry("TimePoint").set(tp)
        
        # Add the filename
        poly_data = new_tp.folder("PolyData[000]")
        poly_data.entry("AbsolutePath").set(os.path.abspath(filename))
        
        return key
    
    def get_main_layer_key(self) -> str:
        """Get the folder id for the main image or raise exception if it does not exist."""
        key = self.find_layer_by_role("MainRole", 0)
        if not key:
            raise ValueError("Main layer not found in workspace")
        return key
    
    def set_layer_nickname(self, layer_key: str, value: str):
        """Set layer nickname."""
        folder = self.registry.folder(layer_key)
        key = "Nickname" if self.is_key_valid_mesh_layer(layer_key) else "LayerMetaData.CustomNickName"
        folder.entry(key).set(value)
    
    def get_tags(self, folder: Registry) -> Set[str]:
        """Get a set of tags from a particular folder."""
        tag_set = set()
        if folder.has_entry("Tags"):
            tags_str = folder.entry("Tags").get("")
            if tags_str:
                tag_set = set(tag.strip() for tag in tags_str.split(",") if tag.strip())
        return tag_set
    
    def put_tags(self, folder: Registry, tags: Set[str]):
        """Put tags into a folder."""
        tags_str = ", ".join(sorted(tags))
        folder.entry("Tags").set(tags_str)
    
    def add_tag(self, folder: Registry, new_tag: str):
        """Add a tag to a particular folder."""
        tags = self.get_tags(folder)
        tags.add(new_tag)
        self.put_tags(folder, tags)
    
    def remove_tag(self, folder: Registry, tag: str):
        """Remove a tag from a folder."""
        tags = self.get_tags(folder)
        tags.discard(tag)
        self.put_tags(folder, tags)
    
    def find_layers_by_tag(self, tag: str) -> List[str]:
        """Find layers that match a tag."""
        matches = []
        
        # Iterate over all image layers
        for i in range(self.get_number_of_layers()):
            key = f"Layers.Layer[{i:03d}]"
            folder = self.registry.folder(key)
            if tag in self.get_tags(folder):
                matches.append(key)
        
        # Iterate over all mesh layers
        for i in range(self.get_number_of_mesh_layers()):
            key = f"MeshLayers.Layer[{i:03d}]"
            folder = self.registry.folder(key)
            if tag in self.get_tags(folder):
                matches.append(key)
        
        return matches
    
    def layer_spec_to_key(self, layer_spec: str) -> str:
        """Translate a shorthand layer specifier to a folder ID."""
        # Basic pattern (001)
        if re.match(r"^\d+$", layer_spec):
            layer_index = int(layer_spec)
            key = f"Layers.Layer[{layer_index:03d}]"
            if not self.registry.has_folder(key):
                raise ValueError(f"Layer {layer_spec} not found in workspace")
            return key
        
        # String:Number pattern (M, S, O:0, etc.)
        match = re.match(r"^([a-zA-Z]+):?(-?\d+)?$", layer_spec)
        if match:
            role_str = match.group(1)
            pos_str = match.group(2)
            pos_in_role = int(pos_str) if pos_str else 0
            
            # Map role strings
            role_map = {
                'M': 'MainRole',
                'S': 'SegmentationRole',
                'O': 'OverlayRole',
                'A': 'AnatomicalRole'
            }
            
            role = role_map.get(role_str.upper())
            if role:
                key = self.find_layer_by_role(role, pos_in_role)
                if key:
                    return key
        
        raise ValueError(f"Layer specification {layer_spec} not found in workspace")
    
    def get_workspace_directory(self) -> str:
        """Get the absolute path to the directory where the workspace was loaded from."""
        return self.workspace_file_dir
    
    def clear_labels(self):
        """Reset the labels - leaves only the clear label."""
        if self.registry.has_folder("IRIS.LabelTable"):
            labels = self.registry.folder("IRIS.LabelTable")
            labels.clear()
            # Add clear label
            labels.entry("NumberOfElements").set(1)
            clear_label = labels.folder("Element[0]")
            clear_label.entry("Index").set(0)
            clear_label.entry("Alpha").set(255)
            clear_label.entry("Red").set(0)
            clear_label.entry("Green").set(0)
            clear_label.entry("Blue").set(0)
            clear_label.entry("Visible").set(1)
            clear_label.entry("Label").set("Clear Label")
    
    def export_workspace(self, new_workspace: str, scramble_filenames: bool = True):
        """
        Export the workspace to a new location, copying all layer images.
        
        Args:
            new_workspace: Path to the new workspace file
            scramble_filenames: If True, use MD5 hash as basename; if False, preserve original names
        """
        # NOTE: C++ creates a copy of the workspace object; we'll deep copy the registry
        # to avoid modifying the original workspace during export
        export_registry = deepcopy(self.registry)
        
        # Convert to absolute path
        ws_file_full = os.path.abspath(new_workspace)
        wsdir = os.path.dirname(ws_file_full)
        
        # Create output directory if it doesn't exist
        os.makedirs(wsdir, exist_ok=True)
        
        # Get number of layers - we need to count from the export registry
        n_layers = 0
        while export_registry.has_folder(f"Layers.Layer[{n_layers:03d}]"):
            n_layers += 1
        
        # Process each layer
        for i in range(n_layers):
            # Get the folder corresponding to the layer
            layer_key = f"Layers.Layer[{i:03d}]"
            f_layer = export_registry.folder(layer_key)
            
            # Get the (possibly moved) absolute filename
            # NOTE: We need to resolve the actual path using the original workspace's paths
            fn_layer = f_layer.entry("AbsolutePath").get("")
            
            # If workspace has moved, try to find the file relative to current location
            if self.moved and self.workspace_saved_dir:
                if fn_layer.startswith(self.workspace_saved_dir):
                    relative_path = fn_layer[len(self.workspace_saved_dir):].lstrip(os.sep)
                else:
                    relative_path = os.path.relpath(fn_layer, self.workspace_saved_dir)
                
                moved_file_full = os.path.abspath(os.path.join(self.workspace_file_dir, relative_path))
                if os.path.isfile(moved_file_full):
                    fn_layer = moved_file_full
            
            # Get the current layer base filename (without extension)
            fn_layer_basename = os.path.splitext(os.path.basename(fn_layer))[0]
            
            # NOTE: C++ has IO hints for reading images in various formats
            # SimpleITK handles most formats automatically, so we skip the hints
            
            # Read the image
            # NOTE: C++ uses GuidedNativeImageIO which handles multiple formats
            # SimpleITK ReadImage should handle most medical image formats
            img = sitk.ReadImage(fn_layer)
            
            # Compute hash of image data if scrambling filenames
            if scramble_filenames:
                # NOTE: C++ uses io->GetNativeImageMD5Hash() which computes hash of image data
                # We'll compute MD5 of the pixel data array
                img_array = sitk.GetArrayFromImage(img)
                md5_hash = hashlib.md5(img_array.tobytes()).hexdigest()
                fn_layer_basename = md5_hash
            
            # Create new filename with layer index and basename
            fn_layer_new = os.path.join(wsdir, f"layer_{i:03d}_{fn_layer_basename}.nii.gz")
            
            # Save the layer as NIfTI
            # NOTE: C++ saves as NIFTI without hints - SimpleITK does this automatically
            sitk.WriteImage(img, fn_layer_new)
            
            # Update the layer folder with the new path
            f_layer.entry("AbsolutePath").set(fn_layer_new)
            
            # Clear IO hints (not necessary for NIFTI)
            if f_layer.has_folder("IOHints"):
                f_layer.folder("IOHints").clear()
        
        # Write the updated workspace file
        # NOTE: C++ uses SaveAsXMLFile which updates paths and metadata
        # We'll manually set the save location and write the registry
        export_registry.entry("SaveLocation").set(wsdir)
        export_registry.write_to_xml_file(ws_file_full)

