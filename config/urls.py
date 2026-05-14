"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from config import error_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('employees.urls')),
    path("erro/503/", error_views.error_503, name="error_503"),
    path("erro/504/", error_views.error_504, name="error_504"),
]

handler403 = "config.error_views.error_403"
handler404 = "config.error_views.error_404"
handler500 = "config.error_views.error_500"
