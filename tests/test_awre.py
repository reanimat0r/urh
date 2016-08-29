import unittest


from urh.awre.FormatFinder import FormatFinder
from urh.awre.components.Address import Address
from urh.awre.components.Flags import Flags
from urh.awre.components.Length import Length
from urh.awre.components.Preamble import Preamble
from urh.awre.components.SequenceNumber import SequenceNumber
from urh.awre.components.Synchronization import Synchronization
from urh.awre.components.Type import Type
from urh.signalprocessing.Participant import Participant
from urh.signalprocessing.ProtocoLabel import ProtocolLabel
from urh.signalprocessing.ProtocolAnalyzer import ProtocolAnalyzer
from urh.signalprocessing.Message import Message


class TestAWRE(unittest.TestCase):
    def setUp(self):
        self.protocol = ProtocolAnalyzer(None)
        with open("./data/awre_consistent_addresses.txt") as f:
            for line in f:
                self.protocol.messages.append(Message.from_plain_bits_str(line.replace("\n", ""), {}))
                self.protocol.messages[-1].message_type = self.protocol.default_message_type

        # Assign participants
        alice = Participant("Alice", "A")
        bob = Participant("Bob", "B")
        alice_indices = {1, 2, 5, 6, 9, 10, 13, 14, 17, 18, 20, 22, 23, 26, 27, 30, 31, 34, 35, 38, 39, 41}
        for i, block in enumerate(self.protocol.messages):
            block.participant = alice if i in alice_indices else bob

        self.participants = [alice, bob]

    def test_build_component_order(self):
        expected_default = [Preamble(), Synchronization(), Length(None), Address(None, None), SequenceNumber(), Type(), Flags()]

        format_finder = FormatFinder(self.protocol)

        for expected, actual in zip(expected_default, format_finder.build_component_order()):
            assert type(expected) == type(actual)

        expected_swapped = [Preamble(), Synchronization(), Address(None, None), Length(None), SequenceNumber(), Type(), Flags()]
        format_finder.length_component.priority = 3
        format_finder.address_component.priority = 2

        for expected, actual in zip(expected_swapped, format_finder.build_component_order()):
            assert type(expected) == type(actual)

        # Test duplicate Priority
        format_finder.sequence_number_component.priority = 5
        with self.assertRaises(ValueError) as context:
            format_finder.build_component_order()
            self.assertTrue('Duplicate priority' in context.exception)
        format_finder.sequence_number_component.priority = 4
        self.assertTrue(format_finder.build_component_order())

        # Test invalid predecessor order
        format_finder.sync_component.priority = 0
        format_finder.preamble_component.priority = 1
        with self.assertRaises(ValueError) as context:
            format_finder.build_component_order()
            self.assertTrue('comes before at least one of its predecessors' in context.exception)
        format_finder.sync_component.priority = 1
        format_finder.preamble_component.priority = 0
        self.assertTrue(format_finder.build_component_order())

    def test_format_finding_rwe(self):
        preamble_start = 0
        preamble_end = 31
        sync_start = 32
        sync_end = 63
        length_start = 64
        length_end = 71

        preamble_label = ProtocolLabel(name="Preamble", start=preamble_start, end=preamble_end, val_type_index=0, color_index=0)
        sync_label = ProtocolLabel(name="Synchronization", start=sync_start, end=sync_end, val_type_index=0, color_index=1)
        length_label = ProtocolLabel(name="Length", start=length_start, end=length_end, val_type_index=0, color_index=2)


        ff = FormatFinder(self.protocol, self.participants)
        found_message_types = ff.perform_iteration()

        self.assertIn(preamble_label, found_message_types[0])
        self.assertIn(sync_label, found_message_types[0])
        self.assertIn(length_label, found_message_types[0])



