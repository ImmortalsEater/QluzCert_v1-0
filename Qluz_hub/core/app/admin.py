from django.contrib import admin
from .models import Colaborador


@admin.register(Colaborador)
class ColaboradorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'email', 'valor_comissao', 'comissao_paga', 'data_registro')
    search_fields = ('nome', 'email')
    list_filter = ('comissao_paga',)
