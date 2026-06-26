from django.db import models


class Colaborador(models.Model):
    nome = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    valor_comissao = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comissao_paga = models.BooleanField(default=False)
    data_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome
