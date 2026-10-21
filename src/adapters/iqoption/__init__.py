"""
Adapter para IQ Option
"""
from .iqoption_adapter import IQOptionAdapter
from .quadcode_compat import create_iq_option, get_profile

__all__ = ["IQOptionAdapter", "create_iq_option", "get_profile"]
