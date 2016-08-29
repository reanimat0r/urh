from collections import defaultdict

import numpy as np
import time

from urh.util.Logger import logger

from urh.awre.components.Address import Address
from urh.awre.components.Component import Component
from urh.awre.components.Flags import Flags
from urh.awre.components.Length import Length
from urh.awre.components.Preamble import Preamble
from urh.awre.components.SequenceNumber import SequenceNumber
from urh.awre.components.Synchronization import Synchronization
from urh.awre.components.Type import Type
from urh.signalprocessing.ProtocolAnalyzer import ProtocolAnalyzer
from urh.cythonext import util

class FormatFinder(object):
    MIN_BLOCKS_PER_CLUSTER = 2 # If there is only one block per cluster it is not very significant

    def __init__(self, protocol: ProtocolAnalyzer, participants=None):
        if participants is not None:
            protocol.auto_assign_participants(participants)

        self.protocol = protocol
        self.bitvectors = [np.array(block.decoded_bits, dtype=np.int8) for block in self.protocol.messages]
        self.len_cluster = self.cluster_lengths()
        self.xor_matrix = self.build_xor_matrix()

        self.preamble_component = Preamble(priority=0)
        self.sync_component = Synchronization(priority=1, predecessors=[self.preamble_component])
        self.length_component = Length(length_cluster=self.len_cluster, priority=2,
                                       predecessors=[self.preamble_component, self.sync_component])
        self.address_component = Address(participant_lut=[block.participant for block in self.protocol.messages],
                                         xor_matrix=self.xor_matrix, priority=3,
                                         predecessors=[self.preamble_component, self.sync_component])
        self.sequence_number_component = SequenceNumber(priority=4, predecessors=[self.preamble_component, self.sync_component])
        self.type_component = Type(priority=5, predecessors=[self.preamble_component, self.sync_component])
        self.flags_component = Flags(priority=6, predecessors=[self.preamble_component, self.sync_component])

    def build_component_order(self):
        """
        Build the order of component based on their priority and predecessors

        :rtype: list of Component
        """
        present_components = [item for item in self.__dict__.values() if isinstance(item, Component) and item.enabled]
        result = [None] * len(present_components)
        used_prios = set()
        for component in present_components:
            index = component.priority % len(present_components)
            if index in used_prios:
                raise ValueError("Duplicate priority: {}".format(component.priority))
            used_prios.add(index)

            result[index] = component

        # Check if predecessors are valid
        for i, component in enumerate(result):
            if any(i < result.index(pre) for pre in component.predecessors):
                raise ValueError("Component {} comes before at least one of its predecessors".format(component))

        return result

    def perform_iteration(self):
        message_types = {0: [i for i in range(len(self.bitvectors))]}
        max_bitvector = max([len(bitvector) for bitvector in self.bitvectors])
        include_ranges_per_message_type = {0: [(0, max_bitvector)]}
        result = {0: []} # Key = message type, value = list of labels

        for component in self.build_component_order():
            # TODO: Creating new message types e.g. for addresses
            for message_type in message_types:
                include_range = include_ranges_per_message_type[message_type]
                lbl = component.find_field(self.bitvectors, include_range, message_types[message_type])
                if lbl:
                    result[message_type].append(lbl)

                    # Update the include ranges for this block
                    # Exclude the new label from consecutive component operations
                    overlapping = next((rng for rng in include_range if any(j in range(*rng) for j in range(lbl.start, lbl.end))))
                    include_range.remove(overlapping)

                    if overlapping[0] != lbl.start:
                        include_range.append((overlapping[0], lbl.start))

                    if overlapping[1] != lbl.end:
                        include_range.append((lbl.end, overlapping[1]))

                    if isinstance(component, Preamble) or isinstance(component, Synchronization):
                        self.length_component.sync_end = lbl.end

        return result

    def cluster_lengths(self):
        """
        This method clusters some bitvectors based on their length. An example output is

        2: [0.5, 1]
        4: [1, 0.75, 1, 1]

        Meaning there were two block lengths: 2 and 4 bit.
        (0.5, 1) means, the first bit was equal in 50% of cases (meaning maximum difference) and bit 2 was equal in all blocks

        A simple XOR would not work as it would be very error prone.

        :param bitvectors:
        :rtype: dict[int, tuple[np.ndarray, int]]
        """

        number_ones = dict()  # dict of tuple. 0 = number ones vector, 1 = number of blocks for this vector
        for vector in self.bitvectors:
            if len(vector) not in number_ones:
                number_ones[len(vector)] = [np.zeros(len(vector), dtype=int), 0]
            number_ones[len(vector)][0] += vector
            number_ones[len(vector)][1] += 1

        # Calculate the relative numbers and normalize the equalness so e.g. 0.3 becomes 0.7
        return {vl: (np.vectorize(lambda x: x if x >= 0.5 else 1 - x)(number_ones[vl][0] / number_ones[vl][1]))
                for vl in number_ones if number_ones[vl][1] >= self.MIN_BLOCKS_PER_CLUSTER}

    def build_xor_matrix(self):
        t = time.time()
        xor_matrix = util.build_xor_matrix(self.bitvectors)
        logger.debug("XOR matrix: {}s".format(time.time()-t))
        return xor_matrix