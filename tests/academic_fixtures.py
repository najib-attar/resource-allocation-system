"""Explicit real administrator reviews for older scheduling regression fixtures.

These tests predate human eligibility and test allocation/calendar behavior.
Security/gate tests call production execute_allocation directly and never use
this helper. No production seeder or service grants eligibility automatically.
"""
import re
from sqlalchemy import inspect, select, text
from web.account_service import AccountService
from web.academic_eligibility import EligibilityService
from web.persistence.models import LoginAccount, RequestEligibility, ResourceRequest, Role, User
from web.allocation_workflow import execute_allocation


def review_requests(database):
    reviewer=900001
    with database.transaction(read_only=True) as session:
        schema=session.scalar(text('SELECT current_schema()'))
        if not re.fullmatch('ras_test_[0-9a-f]{32}',schema or ''):
            raise RuntimeError('Academic fixture review is restricted to owned test schemas.')
        if not inspect(session.connection()).has_table('request_eligibility'):
            return  # An explicitly historical migration fixture before the gate.
        account=session.get(LoginAccount,reviewer)
        keys=[(r.id,r.revision,e.version) for r,e in session.execute(select(ResourceRequest,RequestEligibility)
            .join(RequestEligibility,RequestEligibility.request_id==ResourceRequest.id)
            .where(RequestEligibility.status=='Pending Eligibility Review'))]
    if not keys:return
    if account is None:
        with database.transaction() as session:
            role=session.scalar(select(Role.id).where(Role.name=='Administrator'))
            if role is None:
                row=Role(name='Administrator');session.add(row);session.flush();role=row.id
            session.add(User(id=reviewer,source_order=reviewer,name='Synthetic Eligibility Reviewer',primary_role_id=role))
        AccountService(database).provision(reviewer,'fixture-eligibility-reviewer','Synthetic-review-only-password',administrator=True)
    service=EligibilityService(database)
    for key,revision,version in keys:
        service.decide(reviewer,key,revision,version,True,'Explicit administrative review of synthetic allocation regression input.')


def execute_reviewed_allocation(repository,gateway,*args,**kwargs):
    review_requests(repository.database)
    return execute_allocation(repository,gateway,*args,**kwargs)


def submit_reviewed(client,database,*args,**kwargs):
    """Exercise the new two-step admin workflow in old save/run regressions."""
    response=client.post(*args,**kwargs)
    action=kwargs.get('data',{}).get('submitAction')
    if action in ('save_run','save_review') and response.status_code==302:
        if '/academic-eligibility/' not in response.location:
            raise AssertionError('A new request bypassed eligibility review.')
        key=int(response.location.rstrip('/').rsplit('/',1)[-1])
        review_requests(database)
        return client.post('/run-allocation-now/'+str(key))
    return response


def prepare_historical_gate_replay(database):
    """Remove gate-only synthetic metadata before older migration replay tests.

    The production downgrade refuses history loss. These tests deliberately
    recreate a pre-gate schema, retaining all original application records and
    publications. Their whole random schema is disposable; this is not a
    production rollback path or an allocation/authentication bypass.
    """
    with database.transaction() as session:
        schema=session.scalar(text('SELECT current_schema()'))
        if not re.fullmatch('ras_test_[0-9a-f]{32}',schema or ''):
            raise RuntimeError('Historical replay is restricted to owned test schemas.')
        if inspect(session.connection()).has_table('request_eligibility'):
            for table,name in (('request_eligibility','eligibility_no_truncate'),
                    ('eligibility_event','eligibility_event_no_truncate'),('allocation_eligibility','allocation_eligibility_no_truncate')):
                session.execute(text(f'DROP TRIGGER IF EXISTS {name} ON {table}'))
            session.execute(text('TRUNCATE allocation_eligibility, eligibility_event, request_eligibility'))
            for table,name in (('request_eligibility','eligibility_no_truncate'),
                    ('eligibility_event','eligibility_event_no_truncate'),('allocation_eligibility','allocation_eligibility_no_truncate')):
                session.execute(text(f'CREATE TRIGGER {name} BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION ras_eligibility_immutable()'))
