"""Administrator-only review interface; no engine execution on review."""
from flask import Blueprint, g, redirect, render_template, request, url_for
from .academic_eligibility import EligibilityError, EligibilityService


def create_eligibility_blueprint(database_provider):
    blueprint=Blueprint('eligibility',__name__,url_prefix='/academic-eligibility')

    @blueprint.after_request
    def private(response):
        response.headers['Cache-Control']='private, no-store'
        return response

    @blueprint.errorhandler(EligibilityError)
    def invalid(error):
        return render_template('calendar_error.html',message=str(error)),409

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('calendar_error.html',message=str(error)),403

    @blueprint.get('/')
    def index():
        return render_template('eligibility_queue.html',review=EligibilityService(database_provider()).list_for(g.principal.user_id))

    @blueprint.route('/<int:request_id>',methods=['GET','POST'])
    def detail(request_id):
        service=EligibilityService(database_provider())
        if request.method=='POST':
            try:revision,version=int(request.form.get('revision','')),int(request.form.get('reviewVersion',''))
            except ValueError as error:raise EligibilityError('Refresh to obtain current request/review versions.') from error
            if request.form.get('decision') not in ('approve','reject'):
                raise EligibilityError('Choose approve or reject.')
            service.decide(g.principal.user_id,request_id,revision,version,
                request.form['decision']=='approve',request.form.get('reason',''))
            return redirect(url_for('eligibility.detail',request_id=request_id))
        return render_template('eligibility_review.html',item=service.detail(g.principal.user_id,request_id),
                               history=service.history(g.principal.user_id,request_id))

    return blueprint
