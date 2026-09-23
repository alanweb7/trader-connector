"""Lista conexoes salvas no banco"""
from src.infrastructure.database.connection_repository import connection_repository

conns = connection_repository.list_all()
print(f"Conexoes salvas: {len(conns)}")
for c in conns:
    cid = str(c.get("id", "?"))[:8]
    name = c.get("name", "?")
    broker = c.get("broker", "?")
    atype = c.get("account_type", "?")
    status = c.get("status", "?")
    uid = c.get("user_id", "?")
    email = c.get("email", "?") if "email" in c else "?"
    print(f"  - {cid} | {name} | {broker} | {atype} | status={status} | user={uid} | email={email}")
