from starlette.requests import Request
from starlette.responses import JSONResponse

USERS = {
    "alice": "password123",
    "bob": "secret456",
}


async def login_handler(request: Request) -> JSONResponse:
    body = await request.json()
    user_id = body.get("user_id", "").strip()
    password = body.get("password", "")

    if not user_id or not password:
        return JSONResponse(
            {"success": False, "error": "User ID and password are required"},
            status_code=400,
        )

    if USERS.get(user_id) == password:
        return JSONResponse({"success": True, "user_id": user_id})

    return JSONResponse(
        {"success": False, "error": "Invalid credentials"},
        status_code=401,
    )
