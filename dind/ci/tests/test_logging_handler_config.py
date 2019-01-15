import uuid

from . import base_case


class WhenSendingUnkwnonEvent(
    base_case.ClusterTestCase
):

    def given_an_event_name(self):
        self.event_name = 'test-' + str(uuid.uuid4())

    def becauseWeSendAnUnknownEventName(self):
        self.cluster.consul.event.fire(
            self.event_name, "{}"
        )

    def error_should_be_in_fluentd_output(self):
        for node_name, _ in self.cluster.nodes.items():
            self.assert_container_logs(
                node_name,
                'cluster_fluentd_1',
                "Unknown event name: {}".format(self.event_name)
            )

    def error_should_be_in_handler_file(self):
        # give a chance (3s) to the event to be consumed and logs flushed
        time.sleep(3)
        for node_name, _ in self.cluster.nodes.items():
            self.assert_in_file(
                node_name,
                'cluster_consul_1',
                '/deploy/handler.log',
                "Unknown event name: {}".format(self.event_name)
            )
