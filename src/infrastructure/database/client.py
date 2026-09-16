"""
Supabase client configuration for Broker Gateway
Reads credentials from environment variables for portability
"""
import os
from typing import Optional
from supabase import create_client, Client


_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """
    Get or create Supabase client singleton
    
    Returns:
        Supabase client instance
        
    Raises:
        ValueError: If environment variables are not set
    """
    global _supabase_client
    
    if _supabase_client is not None:
        return _supabase_client
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    
    if not url or not key:
        raise ValueError(
            "Supabase credentials not found. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) "
            "in your .env file."
        )
    
    _supabase_client = create_client(url, key)
    return _supabase_client


def reset_supabase() -> None:
    """Reset the Supabase client (useful for testing)"""
    global _supabase_client
    _supabase_client = None
