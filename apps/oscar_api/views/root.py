from rest_framework.decorators import api_view
from rest_framework import reverse
from rest_framework.response import Response

@api_view(['GET'])
def api_root(request, format=None):
    return Response({
        'products': reverse.reverse('api-product-list', request=request)
    })
