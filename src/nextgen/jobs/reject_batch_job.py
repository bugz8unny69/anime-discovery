"""Reject staged batch episodes through the shared lifecycle."""
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.jobs.reject_execution import registration as shared_registration

KIND='REJECT_BATCH'
DEFINITION=HandlerDefinition(KIND,'Reject all staged batch episodes safely')


def registration():
    return shared_registration(KIND,DEFINITION,batch=True)
