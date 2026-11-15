from sqlalchemy import select
from app.main import only_owned
from app.models import MediaAsset, TranslationJob

def test_social_users_scope_queries_by_job_owner():
    query=only_owned(select(TranslationJob),{"admin":False,"user_id":"user-01"},TranslationJob)
    sql=str(query)
    assert "owner_user_id" in sql

def test_api_key_admin_query_does_not_apply_user_filter():
    query=only_owned(select(TranslationJob),{"admin":True,"user_id":None},TranslationJob)
    assert "WHERE" not in str(query)

def test_media_ownership_query_has_user_predicate():
    query=only_owned(select(MediaAsset),{"admin":False,"user_id":"user-02"},MediaAsset)
    assert "owner_user_id" in str(query)
