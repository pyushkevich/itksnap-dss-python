"""
Python implementation of ITK-SNAP Registry system.

A Registry is a hierarchical tree of key-value pairs, similar to Windows Registry
or a nested dictionary structure. Used for storing workspace configuration.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import re


class RegistryValue:
    """Represents a single value in the registry with optional null state."""
    
    def __init__(self, value: Optional[str] = None):
        self.m_null = value is None
        self.m_string = "" if value is None else str(value)
    
    def is_null(self) -> bool:
        """Check if value is null (not set)."""
        return self.m_null
    
    def get_string(self) -> str:
        """Get the internal string representation."""
        return self.m_string
    
    def get(self, default_value: Any = None) -> Any:
        """Get value with optional default if null."""
        if self.m_null:
            return default_value
        
        # If no default provided, return string
        if default_value is None:
            return self.m_string
        
        # Type conversion based on default type
        if isinstance(default_value, bool):
            return self.m_string.lower() in ('true', '1', 'yes')
        elif isinstance(default_value, int):
            try:
                return int(self.m_string)
            except ValueError:
                return default_value
        elif isinstance(default_value, float):
            try:
                return float(self.m_string)
            except ValueError:
                return default_value
        elif isinstance(default_value, (list, tuple)):
            # Parse space-separated values
            try:
                parts = self.m_string.split()
                if isinstance(default_value[0], int):
                    return type(default_value)([int(p) for p in parts])
                elif isinstance(default_value[0], float):
                    return type(default_value)([float(p) for p in parts])
                else:
                    return type(default_value)(parts)
            except (ValueError, IndexError):
                return default_value
        else:
            return self.m_string
    
    def set(self, value: Any) -> None:
        """Set the value."""
        if isinstance(value, (list, tuple)):
            # Convert list/tuple to space-separated string
            self.m_string = ' '.join(str(v) for v in value)
        else:
            self.m_string = str(value)
        self.m_null = False
    
    def __getitem__(self, default_value: Any) -> Any:
        """Get value with default (legacy support)."""
        return self.get(default_value)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RegistryValue):
            return False
        return self.m_null == other.m_null and self.m_string == other.m_string
    
    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


class Registry:
    """Hierarchical tree of key-value pairs for configuration storage."""
    
    def __init__(self, filename: Optional[str] = None):
        self.m_entry_map: Dict[str, RegistryValue] = {}
        self.m_folder_map: Dict[str, Registry] = {}
        self.m_add_if_not_found = False
        
        if filename:
            self.read_from_file(filename)
    
    def entry(self, key: str) -> RegistryValue:
        """Get or create an entry with the given key."""
        # Handle nested keys with dots
        if '.' in key:
            parts = key.split('.', 1)
            return self.folder(parts[0]).entry(parts[1])
        
        # Return existing entry or create new one
        if key not in self.m_entry_map:
            self.m_entry_map[key] = RegistryValue()
        return self.m_entry_map[key]
    
    def folder(self, key: str) -> Registry:
        """Get or create a subfolder with the given key."""
        # Handle nested keys with dots
        if '.' in key:
            parts = key.split('.', 1)
            return self.folder(parts[0]).folder(parts[1])
        
        # Return existing folder or create new one
        if key not in self.m_folder_map:
            self.m_folder_map[key] = Registry()
            self.m_folder_map[key].m_add_if_not_found = self.m_add_if_not_found
        return self.m_folder_map[key]
    
    def __getitem__(self, key: str) -> RegistryValue:
        """Shorthand for entry access."""
        return self.entry(key)
    
    def has_entry(self, key: str) -> bool:
        """Check if an entry exists."""
        if '.' in key:
            parts = key.split('.', 1)
            if parts[0] in self.m_folder_map:
                return self.m_folder_map[parts[0]].has_entry(parts[1])
            return False
        return key in self.m_entry_map
    
    def has_folder(self, key: str) -> bool:
        """Check if a folder exists."""
        if '.' in key:
            parts = key.split('.', 1)
            if parts[0] in self.m_folder_map:
                return self.m_folder_map[parts[0]].has_folder(parts[1])
            return False
        return key in self.m_folder_map
    
    def get_entry_keys(self) -> List[str]:
        """Get list of all entry keys in this folder."""
        return list(self.m_entry_map.keys())
    
    def get_folder_keys(self) -> List[str]:
        """Get list of all subfolder keys."""
        return list(self.m_folder_map.keys())
    
    def find_folders_from_pattern(self, pattern: str) -> List[str]:
        """Find folder keys matching regex pattern."""
        regex = re.compile(pattern)
        return [key for key in self.m_folder_map.keys() if regex.search(key)]
    
    def clear(self):
        """Remove all entries and subfolders."""
        self.m_entry_map.clear()
        self.m_folder_map.clear()
    
    def is_empty(self) -> bool:
        """Check if registry has no entries or folders."""
        return len(self.m_entry_map) == 0 and len(self.m_folder_map) == 0
    
    def update(self, other: Registry):
        """Update this registry with entries from another."""
        # Update subfolders recursively
        for key, folder in other.m_folder_map.items():
            self.folder(key).update(folder)
        
        # Update entries
        for key, value in other.m_entry_map.items():
            self.m_entry_map[key] = RegistryValue(value.get_string() if not value.is_null() else None)
    
    def collect_keys(self, prefix: str = "") -> List[str]:
        """Recursively collect all keys with optional prefix."""
        keys = []
        
        # Add subfolder keys
        for key, folder in self.m_folder_map.items():
            folder_prefix = f"{prefix}{key}." if prefix else f"{key}."
            keys.extend(folder.collect_keys(folder_prefix))
        
        # Add entry keys
        for key in self.m_entry_map.keys():
            keys.append(f"{prefix}{key}")
        
        return keys
    
    def read_from_xml_file(self, filename: str):
        """Load registry from XML file."""
        tree = ET.parse(filename)
        root = tree.getroot()
        self._parse_xml_node(root)
    
    def _parse_xml_node(self, node: ET.Element):
        """Recursively parse XML nodes."""
        for child in node:
            if child.tag == 'entry':
                key = child.attrib['key']
                value = child.attrib.get('value', '')
                self.m_entry_map[key] = RegistryValue(value)
            elif child.tag == 'folder':
                key = child.attrib['key']
                subfolder = Registry()
                subfolder._parse_xml_node(child)
                self.m_folder_map[key] = subfolder
    
    def write_to_xml_file(self, filename: str, header: Optional[str] = None):
        """Write registry to XML file."""
        with open(filename, 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8" ?>\n')
            if header:
                f.write(f'<!-- {header} -->\n')
            f.write('<!DOCTYPE registry [\n')
            f.write('<!ELEMENT registry (entry*,folder*)>\n')
            f.write('<!ELEMENT folder (entry*,folder*)>\n')
            f.write('<!ELEMENT entry EMPTY>\n')
            f.write('<!ATTLIST folder key CDATA #REQUIRED>\n')
            f.write('<!ATTLIST entry key CDATA #REQUIRED>\n')
            f.write('<!ATTLIST entry value CDATA #REQUIRED>\n')
            f.write(']>\n')
            f.write('<registry>\n')
            self._write_xml(f, '  ')
            f.write('</registry>\n')
    
    def _write_xml(self, file, indent: str):
        """Recursively write XML content."""
        # Write entries
        for key, value in self.m_entry_map.items():
            if not value.is_null():
                encoded_key = self._encode_xml(key)
                encoded_value = self._encode_xml(value.get_string())
                file.write(f'{indent}<entry key="{encoded_key}" value="{encoded_value}" />\n')
        
        # Write subfolders
        for key, folder in self.m_folder_map.items():
            encoded_key = self._encode_xml(key)
            file.write(f'{indent}<folder key="{encoded_key}" >\n')
            folder._write_xml(file, indent + '  ')
            file.write(f'{indent}</folder>\n')
    
    @staticmethod
    def _encode_xml(text: str) -> str:
        """Encode text for XML output."""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&apos;'))
    
    def read_from_file(self, filename: str):
        """Read registry from file (auto-detect XML vs plain text)."""
        path = Path(filename)
        if path.suffix.lower() in ('.xml', '.itksnap'):
            self.read_from_xml_file(filename)
        else:
            # Plain text format not implemented
            raise NotImplementedError("Plain text registry format not yet implemented")
    
    def write_to_file(self, filename: str, header: Optional[str] = None):
        """Write registry to file."""
        self.write_to_xml_file(filename, header)
    
    def print(self, indent: str = "  ", prefix: str = ""):
        """Print registry structure in readable format."""
        # Print folders first
        for key, folder in sorted(self.m_folder_map.items()):
            print(f"{prefix}{key}:")
            folder.print(indent, prefix + indent)
        
        # Print entries
        for key, value in sorted(self.m_entry_map.items()):
            if not value.is_null():
                print(f"{prefix}{key} = {value.get_string()}")
    
    def put_array(self, array: List[Any]):
        """Store an array in registry format."""
        self.entry("ArraySize").set(len(array))
        for i, item in enumerate(array):
            self.entry(f"Element[{i}]").set(item)
    
    def get_array(self, default_element: Any) -> List[Any]:
        """Retrieve an array from registry format."""
        size = self.entry("ArraySize").get(0)
        result = []
        for i in range(size):
            result.append(self.entry(f"Element[{i}]").get(default_element))
        return result
    
    @staticmethod
    def key(format_str: str, *args) -> str:
        """Helper to format registry keys like printf."""
        return format_str % args
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Registry):
            return False
        return (self.m_entry_map == other.m_entry_map and 
                self.m_folder_map == other.m_folder_map)
    
    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)
