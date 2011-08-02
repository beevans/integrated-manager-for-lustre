
from configure.models import JobRecord, StepRecord

class StepPaused(Exception):
    pass

class StepCleanError(Exception):
    """A step encountered an error which prevented it making any changes,
       such the step may be retried at will.  For example, an attempt to
       mkfs over ssh failed to establish a connection: there is no risk that
       mkfs command started running"""
    pass

class StepDirtyError(Exception):
    """A step encountered an error which may have left the system in 
       an inconsistent state.  For example, connectivity was lost partway
       through a mkfs operation: we don't know if the filesystem is formatted
       or not"""
    pass

STEP_PAUSE_DELAY = 10

class Step(object):
    def __init__(self, job_record, args):
        self.args = args
        self.job_record_id = job_record.id

    def is_idempotent(self):
        """Indicate whether the step is idempotent.  For example, mounting 
           a target.  Step subclasses which are idempotent should override this and
           return True."""
        return False

    def wrap_run(self):
        print "Running %s" % self
        job_record = JobRecord.objects.get(id = self.job_record_id)
        if job_record.paused:
            raise StepPaused()
        try:
            return self.run(self.args)
        except Exception, e:
            self.mark_job_errored(e)
            # Re-raise so that celery can record for us that this task failed
            raise e

    def mark_job_errored(self, exception):
        from celery.task.control import revoke

        print "Step %s failed: %s'%s'" % (self, exception.__class__, exception)
        job_record = JobRecord.objects.get(id = self.job_record_id)
        for step_record in job_record.steprecord_set.all():
            # TODO: revoking sends the ID of the task to all workers
            # and they put it in a list of tasks not to action.  But is the task
            # itself somehow pull from the queue when using DB backend?  Or do we
            # depend on the worker staying alive long enough to hit it?  Check!
            # (If the behaviour isn't what we want then revoked tasks my come 
            # back to life after a worker restart!)
            
            # FIXME: revoke is NOOP when using djkombu
            revoke(step_record.task_id, terminate = True)

        job_record.errored = True
        job_record.save()

    def mark_job_complete(self):
        job_record = JobRecord.objects.get(id = self.job_record_id)
        job_record.complete = True
        job_record.save()

    def run(self):
        raise NotImplementedError

class Job(object):
    def __init__(self, steps):
        self.job_record = JobRecord()
        self.job_record.set_steps(steps)

    def run(self):
        self.job_record.run()

class FinalStep(Step):
    def run(self, kwargs):
        self.mark_job_complete()


