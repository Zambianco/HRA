from django.shortcuts import render


def _render_error(request, status_code: int, title: str, description: str):
    response = render(
        request,
        "errors/error_page.html",
        {
            "status_code": status_code,
            "error_title": title,
            "error_description": description,
        },
        status=status_code,
    )
    return response


def error_403(request, exception):
    return _render_error(
        request,
        403,
        "Acesso negado",
        "Voce nao tem permissao para acessar este recurso.",
    )


def error_404(request, exception):
    return _render_error(
        request,
        404,
        "Pagina nao encontrada",
        "O endereco solicitado nao existe ou foi movido.",
    )


def error_500(request):
    return _render_error(
        request,
        500,
        "Erro interno",
        "Ocorreu um erro interno ao processar a solicitacao.",
    )


def error_503(request):
    return _render_error(
        request,
        503,
        "Servico indisponivel",
        "O servico esta temporariamente indisponivel. Tente novamente.",
    )


def error_504(request):
    return _render_error(
        request,
        504,
        "Tempo esgotado",
        "A resposta demorou mais do que o esperado. Tente novamente.",
    )
