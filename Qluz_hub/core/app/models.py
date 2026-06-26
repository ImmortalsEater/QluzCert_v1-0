from django.db import models


class Colaborador(models.Model):
    nome = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    valor_comissao = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comissao_paga = models.BooleanField(default=False)
    data_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome


class PlanilhaRegistro(models.Model):
    data_venda = models.DateField(null=True, blank=True)
    contador_parceiro = models.CharField(max_length=255, blank=True)
    contador_contabilidade = models.CharField(max_length=255, blank=True)
    telefone1 = models.CharField(max_length=50, blank=True)
    cliente = models.CharField(max_length=255, blank=True)
    cpf_cnpj = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    telefone2 = models.CharField(max_length=50, blank=True)
    tipo_certificado = models.CharField(max_length=255, blank=True)
    valor_venda = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    percentual_comissao = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    valor_comissao = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    pago_comissao = models.BooleanField(default=False)
    chave_pix = models.CharField(max_length=255, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    pago_venda = models.BooleanField(default=False)
    forma_pagamento = models.CharField(max_length=255, blank=True)
    banco = models.CharField(max_length=255, blank=True)
    certificado_feito = models.CharField(max_length=255, blank=True)
    venda = models.CharField(max_length=255, blank=True)
    custo_certificado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_liquido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.cliente} <{self.email}>"
