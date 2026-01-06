import logging

class SilenceProgressEndpointLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/rag/progress/"):
            logger = logging.getLogger("django.server")
            old_handlers = logger.handlers
            old_level = logger.level
            old_propagate = logger.propagate

            try:
                logger.handlers = [logging.NullHandler()]
                logger.setLevel(logging.CRITICAL)
                logger.propagate = False
                return self.get_response(request)
            finally:
                logger.handlers = old_handlers
                logger.setLevel(old_level)
                logger.propagate = old_propagate

        return self.get_response(request)
