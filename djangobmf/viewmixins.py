#!/usr/bin/python
# ex:set fileencoding=utf-8:

from __future__ import unicode_literals

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.core.urlresolvers import reverse_lazy
from django.core.urlresolvers import NoReverseMatch
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.timezone import now
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.defaults import permission_denied

from djangobmf import get_version
from djangobmf.decorators import login_required
from djangobmf.models import Notification
from djangobmf.utils import get_model_from_cfg

import json
import datetime
try:
    from urllib import parse
except ImportError:
    import urlparse as parse


class BaseMixin(object):
    """
    provides functionality used in EVERY view throughout the application.
    this is used so we don't neet to define a middleware
    """

    def get_permissions(self, permissions):
        """
        returns a list of (django) permissions and use them in dispatch to
        determinate if the user can view the page, he requested
        """
        return permissions

    def check_permissions(self):
        """
        overwrite this function to add a view permission check (i.e
        one which depends on the object or on the request)
        """
        return True

    def read_session_data(self):
        return self.request.session.get("djangobmf", {'version': get_version()})

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        """
        checks permissions, requires a login and
        because we are using a generic view approach to the data-models
        in django BMF, we can ditch a middleware (less configuration)
        and add the functionality to this function.
        """

        if not self.check_permissions() or not self.request.user.has_perms(self.get_permissions([])):
            return permission_denied(self.request)

        # === EMPLOYEE ====================================================

        employee = get_model_from_cfg('EMPLOYEE')
        if employee:
            try:
                self.request.user.djangobmf_employee = employee.objects.get(user=self.request.user)
            except employee.DoesNotExist:
                # the user does not have permission to view the bmf
                if self.request.user.is_superuser:
                    return redirect('djangobmf:wizard', permanent=False)
                else:
                    raise PermissionDenied
        else:
            self.request.user.djangobmf_employee = None

        # === TEAM ========================================================

        team = get_model_from_cfg('TEAM')
        if team:
            self.request.user.djangobmf_teams = \
                team.objects.filter(members=self.request.user.djangobmf_employee).values_list("id", flat=1)
        else:
            self.request.user.djangobmf_teams = None

        return super(BaseMixin, self).dispatch(*args, **kwargs)


class ViewMixin(BaseMixin):

    def write_session_data(self, data, modify=False):
        # reload sessiondata, because we can not be sure, that the
        # session was not changed during this function (update_notification)
        session_data = self.read_session_data()
        session_data.update(data)

        # update session
        self.request.session["djangobmf"] = session_data
        if modify:
            self.request.session.modified = True

    def get_context_data(self, **kwargs):
        kwargs.update({
            'djangobmf': self.read_session_data()
        })
        # allways read current version, if in development mode
        if settings.DEBUG:
            kwargs["djangobmf"]['version'] = get_version()
        return super(BaseMixin, self).get_context_data(**kwargs)

    def update_notification(self, check_object=True):
        """
        This function is used by django BMF to update the notifications
        used in the BMF-Framework
        """
        if check_object \
                and not self.object.djangobmf_notification.filter(
                    user=self.request.user,
                    unread=True,
                ).update(unread=None, changed=now()):
            return None

        # get all session data
        session_data = self.read_session_data()

        # manipulate session
        session_data["notification_last_update"] = datetime.datetime.utcnow().isoformat()
        session_data["notification_count"] = Notification.objects.filter(unread=True, user=self.request.user).count()

        # update session
        self.write_session_data(session_data)

    def update_dashboard(self, pk=None):
        """
        This function is used by django BMF to update the dashboards.
        provide a primary key, if you don't want to set an active
        dashboard.
        """
        session_data = self.read_session_data()
        from .dashboard.models import Dashboard

        session_data["dashboard"] = []
        session_data["dashboard_current"] = None

        update_views = False

        for d in Dashboard.objects.filter(user=self.request.user, name__isnull=False):
            data = {'pk': d.pk, 'name': d.name}
            if pk and int(pk) == d.pk:
                session_data['dashboard_current'] = data
                update_views = True
            session_data['dashboard'].append(data)

        # update session
        self.write_session_data(session_data)

        if update_views:
            self.update_views()

    def update_views(self):
        """
        This function is used by django BMF to update the views.
        just call it, if you need it
        """
        session_data = self.read_session_data()
        from .dashboard.models import View

        # can only be done if a current dashboard is loaded
        if not session_data.get('dashboard_current', None):
            return None
        session_data['views'] = []

        for d in View.objects.filter(dashboard_id=session_data['dashboard_current']['pk']):
            try:
                data = {'pk': d.pk, 'name': d.name, 'category': d.category, 'url': d.get_absolute_url()}
            except NoReverseMatch:
                data = {'pk': d.pk, 'name': d.name, 'category': d.category, 'url': '#'}  # TODO
                continue
            session_data['views'].append(data)

        # update session
        self.write_session_data(session_data)

    def dispatch(self, *args, **kwargs):
        """
        """
        function = super(ViewMixin, self).dispatch(*args, **kwargs)

        if self.request.user.is_anonymous():
            return function

        session_data = self.read_session_data()

        # === NOTIFICATION ================================================

        if 'notification_last_update' in session_data:
            diff = (
                datetime.datetime.utcnow() - datetime.datetime.strptime(
                    session_data['notification_last_update'],
                    '%Y-%m-%dT%H:%M:%S.%f'
                )
            ).total_seconds()
            if diff >= 300:
                self.update_notification(False)
        else:
            self.update_notification(False)

        # === MESSAGE =====================================================

        session_data["message_count"] = 0

        # === DASHBOARD AND VIEWS =========================================

        if 'dashboard' not in session_data:
            self.update_dashboard()

        return function


class AjaxMixin(BaseMixin):
    """
    add some basic function for ajax requests
    """
    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super(AjaxMixin, self).dispatch(*args, **kwargs)

    def check_permissions(self):
        return self.request.is_ajax() and super(AjaxMixin, self).check_permissions()

    def render_to_json_response(self, context, **response_kwargs):
        data = json.dumps(context, cls=DjangoJSONEncoder)
        response_kwargs['content_type'] = 'application/json'
        return HttpResponse(data, **response_kwargs)


class NextMixin(object):
    """
    redirects to an url or to next, if it is set via get
    """

    def redirect_next(self, reverse, *args, **kwargs):
        redirect_to = self.request.REQUEST.get('next', '')

        netloc = parse.urlparse(redirect_to)[1]
        if netloc and netloc != self.request.get_host():
            redirect_to = None

        if redirect_to:
            return redirect_to

        if hasattr(self, 'success_url') and self.success_url:
            return self.success_url

        return reverse_lazy(reverse, args=args, kwargs=kwargs)


# PERMISSIONS

class ModuleViewPermissionMixin(object):
    """
    Checks view permissions of an bmfmodule
    """

    def get_permissions(self, perms):
        info = self.model._meta.app_label, self.model._meta.model_name
        perms.append('%s.view_%s' % info)
        return super(ModuleViewPermissionMixin, self).get_permissions(perms)


class ModuleCreatePermissionMixin(object):
    """
    Checks create permissions of an bmfmodule
    """

    def get_permissions(self, perms):
        info = self.model._meta.app_label, self.model._meta.model_name
        perms.append('%s.add_%s' % info)
        perms.append('%s.view_%s' % info)
        return super(ModuleCreatePermissionMixin, self).get_permissions(perms)


class ModuleClonePermissionMixin(object):
    """
    Checks create permissions of an bmfmodule
    """

    def get_permissions(self, perms):
        info = self.model._meta.app_label, self.model._meta.model_name
        perms.append('%s.clone_%s' % info)
        perms.append('%s.view_%s' % info)
        return super(ModuleClonePermissionMixin, self).get_permissions(perms)


class ModuleUpdatePermissionMixin(object):
    """
    Checks update permissions of an bmfmodule
    """

    def check_permissions(self):
        return self.get_object()._bmfworkflow._current_state.update \
            and super(ModuleUpdatePermissionMixin, self).check_permissions()

    def get_permissions(self, perms):
        info = self.model._meta.app_label, self.model._meta.model_name
        perms.append('%s.change_%s' % info)
        perms.append('%s.view_%s' % info)
        return super(ModuleUpdatePermissionMixin, self).get_permissions(perms)


class ModuleDeletePermissionMixin(object):
    """
    Checks delete permission of an bmfmodule
    """

    def check_permissions(self):
        return self.get_object()._bmfworkflow._current_state.delete \
            and super(ModuleDeletePermissionMixin, self).check_permissions()

    def get_permissions(self, perms):
        info = self.model._meta.app_label, self.model._meta.model_name
        perms.append('%s.delete_%s' % info)
        perms.append('%s.view_%s' % info)
        return super(ModuleDeletePermissionMixin, self).get_permissions(perms)


# MODULES

class ModuleBaseMixin(object):
    model = None

    def get_queryset(self):
        if self.queryset is not None:
            queryset = self.queryset
            if isinstance(queryset, QuerySet):
                queryset = queryset.all()
        elif self.model is not None:
            queryset = self.model._default_manager.all()
        else:
            raise ImproperlyConfigured(
                "%(cls)s is missing a QuerySet. Define "
                "%(cls)s.model, %(cls)s.queryset, or override "
                "%(cls)s.get_queryset()." % {
                    'cls': self.__class__.__name__
                }
            )
        return self.model.has_permissions(queryset, self.request.user)

    def get_object(self):
        if hasattr(self, 'object'):
            return self.object
        return super(ModuleBaseMixin, self).get_object()

    def get_context_data(self, **kwargs):
        info = self.model._meta.app_label, self.model._meta.model_name
        kwargs.update({
            'bmfmodule': {
                'namespace_index': self.model._bmfmeta.url_namespace + ':index',
                'verbose_name_plural': self.model._meta.verbose_name_plural,
                'create_views': self.model._bmfmeta.create_views,
                'model': self.model,
                'has_report': self.model._bmfmeta.has_report,
                'can_clone': self.model._bmfmeta.can_clone and self.request.user.has_perms([
                    '%s.view_%s' % info,
                    '%s.clone_%s' % info,
                ]),
                # 'namespace': self.model._bmfmeta.url_namespace,  # unused
                # 'verbose_name': self.model._meta.verbose_name,  # unused
            },
        })
        if hasattr(self, 'object') and self.object:
            kwargs.update({
                'bmfworkflow': {
                    'enabled': bool(len(self.model._bmfworkflow._transitions)),
                    'state': self.object._bmfworkflow._current_state,
                    'transitions': self.object._bmfworkflow._from_here(self.object, self.request.user),
                },
            })
        return super(ModuleBaseMixin, self).get_context_data(**kwargs)


class ModuleAjaxMixin(ModuleBaseMixin, AjaxMixin):
    """
    base mixin for update, clone and create views (ajax-forms)
    and form-api
    """

    def get_ajax_context(self, context):
        ctx = {
            'object_pk': 0,
            'status': 'ok',  # "ok" for normal html, "valid" for valid forms, "error" if an error occured
            'html': '',
            'message': '',
            'redirect': '',
        }
        ctx.update(context)
        return ctx

    def render_to_response(self, context, **response_kwargs):
        response = super(ModuleAjaxMixin, self).render_to_response(context, **response_kwargs)
        response.render()
        ctx = self.get_ajax_context({
            'html': response.rendered_content,
        })
        return self.render_to_json_response(ctx)

    def render_valid_form(self, context):
        ctx = self.get_ajax_context({
            'status': 'valid',
            # 'redirect': self.get_success_url(),
        })
        ctx.update(context)
        return self.render_to_json_response(ctx)


class ModuleViewMixin(ModuleBaseMixin, ViewMixin):
    """
    Basic objects, includes bmf-specific functions and context
    variables for bmf-views
    """
    pass
