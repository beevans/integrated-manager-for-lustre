#
# INTEL CONFIDENTIAL
#
# Copyright 2013 Intel Corporation All Rights Reserved.
#
# The source code contained or described herein and all documents related
# to the source code ("Material") are owned by Intel Corporation or its
# suppliers or licensors. Title to the Material remains with Intel Corporation
# or its suppliers and licensors. The Material contains trade secrets and
# proprietary and confidential information of Intel or its suppliers and
# licensors. The Material is protected by worldwide copyright and trade secret
# laws and treaty provisions. No part of the Material may be used, copied,
# reproduced, modified, published, uploaded, posted, transmitted, distributed,
# or disclosed in any way without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be
# express and approved by Intel in writing.


from django.contrib.contenttypes.models import ContentType
from tastypie.resources import ModelResource, Resource
from tastypie import fields
from tastypie.authorization import DjangoAuthorization
from tastypie.validation import Validation

from chroma_api.authentication import AnonymousAuthentication
from chroma_core.models import Job, StateLock
from chroma_core.services.job_scheduler.job_scheduler_client import JobSchedulerClient


class StateLockResource(Resource):
    locked_item_id = fields.IntegerField()
    locked_item_content_type_id = fields.IntegerField()
    locked_item_uri = fields.CharField()

    def dehydrate_locked_item_id(self, bundle):
        return bundle.obj.locked_item.id

    def dehydrate_locked_item_content_type_id(self, bundle):
        locked_item = bundle.obj.locked_item
        if hasattr(locked_item, 'content_type'):
            return locked_item.content_type.id
        else:
            return ContentType.objects.get_for_model(locked_item)

    def dehydrate_locked_item_uri(self, bundle):
        from chroma_api.urls import api
        locked_item = bundle.obj.locked_item
        if hasattr(locked_item, 'content_type'):
            locked_item = locked_item.downcast()

        return api.get_resource_uri(locked_item)

    class Meta:
        object_class = StateLock
        resource_name = 'state_lock'
        authorization = DjangoAuthorization()
        authentication = AnonymousAuthentication()


class JobValidation(Validation):
    def is_valid(self, bundle, request = None):
        errors = {}
        try:
            job = Job.objects.get(pk = bundle.data['id']).downcast()
        except KeyError:
            errors['id'] = "Attribute mandatory"
        except Job.DoesNotExist:
            errors['id'] = "Job with id %s not found" % bundle.data['id']
        else:
            try:
                new_state = bundle.data['state']
            except KeyError:
                errors['state'] = "Attribute mandatory"
            else:
                valid_states = ['cancelled', job.state]
                if not new_state in valid_states:
                    errors['state'] = "Must be one of %s" % valid_states

        return errors


class JobResource(ModelResource):
    """
    Jobs refer to individual units of work that the server is doing.  Jobs
    may either run as part of a Command, or on their own.  Jobs which are necessary
    to the completion of more than one command may belong to more than one command.

    For example:

    * a Command to start a filesystem has a Job for starting each OST.
    * a Command to setup an OST has a series of Jobs for formatting, registering etc

    Jobs which are part of the same command may run in parallel to one another.

    The lock objects in the ``read_locks`` and ``write_locks`` fields have the
    following form:

    ::

        {
            id: "1",
            locked_item_id: 2,
            locked_item_content_type_id: 4,
        }

    The ``id`` and ``content_type_id`` of the locked object form a unique identifier
    which can be compared with API-readable objects which have such attributes.
    """

    description = fields.CharField(help_text = "Human readable string around\
            one sentence long describing what the job is doing")
    wait_for = fields.ListField('wait_for', null = True,
            help_text = "List of other jobs which must complete before this job can run")
    read_locks = fields.ListField(null = True,
            help_text = "List of objects which must stay in the required state while\
            this job runs")
    write_locks = fields.ListField(null = True,
            help_text = "List of objects which must be in a certain state for\
            this job to run, and may be modified by this job while it runs.")
    commands = fields.ToManyField('chroma_api.command.CommandResource',
            lambda bundle: bundle.obj.command_set.all(), null = True,
            help_text = "Commands which require this job to complete\
            sucessfully in order to succeed themselves")
    steps = fields.ToManyField('chroma_api.step.StepResource',
            lambda bundle: bundle.obj.stepresult_set.all(), null = True,
            help_text = "Steps executed within this job")
    class_name = fields.CharField(help_text = "Internal class name of job")

    available_transitions = fields.DictField()

    def _dehydrate_locks(self, bundle, write):
        import json

        if bundle.obj.locks_json:
            locks = json.loads(bundle.obj.locks_json)
            locks = [StateLock.from_dict(bundle.obj, lock) for lock in locks if lock['write'] == write]
            slr = StateLockResource()
            return [slr.full_dehydrate(slr.build_bundle(obj = l)).data for l in locks]
        else:
            return []

    def dehydrate_wait_for(self, bundle):
        import json
        if not bundle.obj.wait_for_json:
            return []
        else:
            wait_fors = json.loads(bundle.obj.wait_for_json)
            return [JobResource().get_resource_uri(Job.objects.get(pk=i)) for i in wait_fors]

    def dehydrate_read_locks(self, bundle):
        return self._dehydrate_locks(bundle, write = False)

    def dehydrate_write_locks(self, bundle):
        return self._dehydrate_locks(bundle, write = True)

    def dehydrate_class_name(self, bundle):
        return bundle.obj.content_type.model_class().__name__

    def dehydrate_available_transitions(self, bundle):
        job = bundle.obj.downcast()
        if job.state == 'complete' or not job.cancellable:
            return []
        elif job.cancellable:
            return [{'state': 'cancelled', 'label': 'Cancel'}]

    def dehydrate_description(self, bundle):
        return bundle.obj.downcast().description()

    class Meta:
        queryset = Job.objects.all()
        resource_name = 'job'
        authorization = DjangoAuthorization()
        authentication = AnonymousAuthentication()
        excludes = ['task_id', 'locks_json', 'wait_for_json']
        ordering = ['created_at']
        list_allowed_methods = ['get']
        detail_allowed_methods = ['get', 'put']
        filtering = {'id': ['exact', 'in'], 'state': ['exact']}
        always_return_data = True
        validation = JobValidation()

    def obj_update(self, bundle, request, **kwargs):
        job = Job.objects.get(pk = kwargs['pk'])
        new_state = bundle.data['state']

        if new_state == 'cancelled':
            JobSchedulerClient.cancel_job(job.pk)
            Job.objects.get(pk = kwargs['pk'])

        bundle.obj = job
        return bundle
