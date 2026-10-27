"""Reject staged single-episode media through the shared lifecycle."""
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.jobs.reject_execution import registration as shared_registration

KIND='REJECT_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Reject anime and remove selected staged video')


def registration():
    return shared_registration(KIND,DEFINITION,batch=False)
