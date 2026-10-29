from django.contrib import admin
from django.urls import path, include

from track.auth import ThrottledLoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', ThrottledLoginView.as_view(), name='login'),
    path('', include('django.contrib.auth.urls')),
    path('', include('track.urls')),
]
