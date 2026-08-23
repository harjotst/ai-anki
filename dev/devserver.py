"""The app, with a local signing key standing in for Supabase.

Only for driving the UI by hand: the verifier is real and the tokens are real,
they are simply signed by a key that lives here rather than at the provider.
"""
import json, os, sys, time
sys.path.insert(0, ".")

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa

from app import identity
from app.main import create_app

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER, AUDIENCE, KID = "https://local.test/auth/v1", "authenticated", "dev"

def jwks():
    return {"keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True),
                      "kid": KID, "use": "sig", "alg": "RS256"}]}

def token(sub="00000000-0000-0000-0000-0000000000aa"):
    now = int(time.time())
    return jwt.encode({"sub": sub, "iss": ISSUER, "aud": AUDIENCE, "iat": now,
                       "exp": now + 86400, "email": "dev@local.test"},
                      KEY, algorithm="RS256", headers={"kid": KID})

open(os.environ.get("DEV_TOKEN_FILE", "/tmp/dev-token.txt"), "w").write(token())

app = create_app(
    database_url=os.environ["AI_ANKI_DATABASE_URL"],
    data_dir=os.environ.get("AI_ANKI_DATA_DIR", ".local/uploads"),
    verifier=identity.Verifier(issuer=ISSUER, audience=AUDIENCE, fetch_keys=jwks),
)

# Hand any local client a signed token, so neither the browser nor the phone
# needs one pasted in. Development only: this file never runs in production,
# and the token is only good against this process's throwaway key anyway.
@app.get("/dev/token")
def dev_token():
    from fastapi.responses import JSONResponse

    # no-store, because in real mode this same path is answered by the SPA
    # catch-all and a cached copy of that answer breaks the dev sign-in.
    return JSONResponse({"token": token()}, headers={"cache-control": "no-store"})

# Registered after the SPA catch-all, which would otherwise swallow it.
app.router.routes.insert(0, app.router.routes.pop())

if __name__ == "__main__":
    # All interfaces, not loopback: a real phone on the same Wi-Fi reaches
    # the API at the Mac's LAN address, which loopback would never answer.
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
