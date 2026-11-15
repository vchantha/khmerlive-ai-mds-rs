"""Optional social sign-in / account linking with OAuth 2.0 / OIDC.

Requires server-side configured provider credentials, signed browser session,
and PostgreSQL-backed user identities. No provider access tokens are stored.
Legacy API key is a trusted-admin path for local MVP compatibility.
"""
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.db import SessionLocal
from app.models import AppUser, SocialIdentity

router=APIRouter(prefix="/api/auth",tags=["authentication"])
oauth=OAuth()

def providers():
    result=[]
    for name in ("google","facebook","github"):
        ready=bool(getattr(settings,f"{name}_client_id") and getattr(settings,f"{name}_client_secret"))
        result.append({"id":name,"name":name.capitalize(),"enabled":ready})
    return result

def client_for(name:str):
    if name not in ("google","facebook","github"):
        raise HTTPException(404,"Unknown login provider")
    if not getattr(settings,f"{name}_client_id") or not getattr(settings,f"{name}_client_secret"):
        raise HTTPException(503,f"{name.capitalize()} sign-in is not configured")
    existing=oauth.create_client(name)
    if existing:
        return existing
    params={"name":name,
            "client_id":getattr(settings,f"{name}_client_id"),
            "client_secret":getattr(settings,f"{name}_client_secret")}
    if name=="google":
        params.update(server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                      client_kwargs={"scope":"openid email profile"})
    elif name=="github":
        params.update(authorize_url="https://github.com/login/oauth/authorize",
                      access_token_url="https://github.com/login/oauth/access_token",
                      api_base_url="https://api.github.com/",
                      client_kwargs={"scope":"read:user user:email"})
    else:
        params.update(authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
                      access_token_url="https://graph.facebook.com/v21.0/oauth/access_token",
                      api_base_url="https://graph.facebook.com/v21.0/",
                      client_kwargs={"scope":"public_profile,email"})
    oauth.register(**params)
    return oauth.create_client(name)

def actor_from_request(request:Request, x_api_key:str|None=None):
    # Prefer a signed-in identity even when an old API key is cached by the browser.
    # This prevents an ordinary user session from accidentally taking admin scope.
    user_id=request.session.get("user_id")
    if user_id:
        with SessionLocal() as db:
            if db.get(AppUser,user_id) is None:
                request.session.clear()
                raise HTTPException(401,"Session expired; please sign in")
        return {"admin":False,"user_id":user_id}
    if x_api_key and x_api_key==settings.api_key:
        return {"admin":True,"user_id":None}
    raise HTTPException(401,"Sign in or provide your API key")

@router.get("/providers")
def list_providers():
    return {"providers":providers(),"mode":"social_oauth"}

@router.get("/me")
def me(request:Request):
    user_id=request.session.get("user_id")
    if not user_id:
        return {"authenticated":False,"user":None,"identities":[]}
    with SessionLocal() as db:
        user=db.get(AppUser,user_id)
        if user is None:
            request.session.clear()
            return {"authenticated":False,"user":None,"identities":[]}
        linked=db.scalars(select(SocialIdentity).where(SocialIdentity.user_id==user.id)).all()
        return {"authenticated":True,"user":{"id":user.id,"name":user.display_name,
            "email":user.email,"avatar_url":user.avatar_url},
            "identities":[{"provider":i.provider,"display_name":i.display_name} for i in linked]}

@router.get("/login/{provider}")
async def login(request:Request,provider:str):
    client=client_for(provider)
    # Authlib stores and validates OAuth state in the signed browser session.
    redirect=settings.auth_public_base_url.rstrip("/")+f"/api/auth/callback/{provider}"
    return await client.authorize_redirect(request,redirect)

@router.get("/link/{provider}")
async def link(request:Request,provider:str):
    actor=actor_from_request(request)
    if actor["admin"]:
        raise HTTPException(400,"API-key admin cannot link a social identity; sign in as a user")
    request.session["link_user_id"]=actor["user_id"]
    client=client_for(provider)
    redirect=settings.auth_public_base_url.rstrip("/")+f"/api/auth/callback/{provider}"
    return await client.authorize_redirect(request,redirect)

@router.get("/callback/{provider}")
async def callback(request:Request,provider:str):
    client=client_for(provider)
    try:
        token=await client.authorize_access_token(request)
        if provider=="google":
            profile=token.get("userinfo")
            if not profile:
                profile=await client.userinfo(token=token)
            subject=str(profile["sub"])
            name=str(profile.get("name") or "Google user")[:200]
            email=str(profile.get("email") or "")[:320] or None
            avatar=str(profile.get("picture") or "")[:1000] or None
        elif provider=="github":
            resp=await client.get("user",token=token)
            resp.raise_for_status()
            profile=resp.json()
            subject=str(profile["id"])
            name=str(profile.get("name") or profile.get("login") or "GitHub user")[:200]
            email=str(profile.get("email") or "")[:320] or None
            avatar=str(profile.get("avatar_url") or "")[:1000] or None
        else:
            resp=await client.get("me",params={"fields":"id,name,email,picture"},token=token)
            resp.raise_for_status()
            profile=resp.json()
            subject=str(profile["id"])
            name=str(profile.get("name") or "Facebook user")[:200]
            email=str(profile.get("email") or "")[:320] or None
            avatar=profile.get("picture",{}).get("data",{}).get("url")
            avatar=str(avatar)[:1000] if avatar else None
    except Exception as exc:
        raise HTTPException(400,"Social sign-in was not completed; retry authentication") from exc
    link_user_id=request.session.pop("link_user_id",None)
    with SessionLocal() as db:
        identity=db.scalar(select(SocialIdentity).where(
            SocialIdentity.provider==provider,SocialIdentity.subject==subject))
        if link_user_id:
            if db.get(AppUser,link_user_id) is None:
                raise HTTPException(401,"Linking session expired")
            if identity and identity.user_id!=link_user_id:
                raise HTTPException(409,"This social account is linked to another user")
            existing_provider=db.scalar(select(SocialIdentity).where(
                SocialIdentity.user_id==link_user_id,SocialIdentity.provider==provider))
            if existing_provider and existing_provider.subject!=subject:
                raise HTTPException(409,"A different account is already linked for this provider")
            user=db.get(AppUser,link_user_id)
            if not identity:
                db.add(SocialIdentity(id=str(uuid.uuid4()),user_id=user.id,
                    provider=provider,subject=subject,display_name=name))
        elif identity:
            user=db.get(AppUser,identity.user_id)
        else:
            user=AppUser(id=str(uuid.uuid4()),display_name=name,email=email,avatar_url=avatar)
            db.add(user)
            db.add(SocialIdentity(id=str(uuid.uuid4()),user_id=user.id,
                provider=provider,subject=subject,display_name=name))
        db.commit()
        request.session.clear()
        request.session["user_id"]=user.id
    return RedirectResponse(url="/?auth=connected",status_code=303)

@router.post("/logout")
def logout(request:Request):
    request.session.clear()
    return {"authenticated":False}
