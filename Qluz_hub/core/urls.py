"""
URL configuration for core project.

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
from django.urls import path

from core.app_Gestor.views import DashboardView, sincronizar_drive, editar_google_row, ParceirosView, app_state, app_state_drive, app_state_download

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', DashboardView.as_view(), name='dashboard'),
    path('parceiros/', ParceirosView.as_view(), name='parceiros'),
    path('sincronizar/', sincronizar_drive, name='sincronizar_drive'),
    path('planilha/editar/<int:pk>/', editar_google_row, name='editar_google_row'),
    path('app_state/', app_state, name='app_state'),
    path('app_state_drive/', app_state_drive, name='app_state_drive'),
    path('app_state_download/', app_state_download, name='app_state_download'),
]
