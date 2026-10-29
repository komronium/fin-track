from django.conf import settings
from django.contrib.auth.views import LoginView
from django.core.cache import cache

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60


def client_ip(request):
    """Behind nginx the socket peer is nginx itself; X-Real-IP is only trusted when that is configured."""
    if getattr(settings, 'TRUST_PROXY_HEADERS', False):
        return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
    return request.META.get('REMOTE_ADDR', '')


class ThrottledLoginView(LoginView):
    """Stops password guessing: after 5 failures for one username from one address, wait 15 minutes."""

    def throttle_key(self):
        username = (self.request.POST.get('username') or '').strip().lower()[:150]
        return f'login-fail:{client_ip(self.request)}:{username}'

    def post(self, request, *args, **kwargs):
        if cache.get(self.throttle_key(), 0) >= MAX_FAILED_LOGINS:
            context = self.get_context_data(form=self.get_form(), throttled=True)
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self.throttle_key()
        cache.add(key, 0, LOCKOUT_SECONDS)
        try:
            cache.incr(key)
        except ValueError:  # expired between add() and incr()
            cache.set(key, 1, LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self.throttle_key())
        return super().form_valid(form)
