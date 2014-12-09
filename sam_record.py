import re
import logging
import sys

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] [%(name)s] [%(process)d] %(message)s')
console_handler.setFormatter(formatter)
LOGGER.addHandler(console_handler)


PHRED_SANGER_OFFSET = 33
CIGAR_RE = re.compile('[0-9]+[MIDNSHPX=]')
SEQ_PAD_CHAR = '-'
QUAL_PAD_CHAR = ' '     # This is the ASCII character right blow lowest PHRED quality score in Sanger qualities  (-1)


class SamRecord:


    def __init__(self, ref_len):
        self.ref_len = ref_len
        self.qname = None
        self.flag = None
        self.seq = None
        self.cigar = None
        self.mapq = None
        self.qual = None
        self.pos = None
        self.mate_record = None
        self.nopad_noinsert_seq = None
        self.nopad_noinsert_qual = None
        self.ref_pos_to_insert_seq_qual = None
        self.seq_end_wrt_ref = None
        self.ref_align_len = 0  # includes deletions wrt reference.  Excludes insertions wrt reference
        self.seq_align_len = 0  # includes insertions wrt reference.  Excludes deletions wrt reference

    def is_empty(self):
        return not self.qname and not self.seq

    def fill_record(self, sam_row_dict):
        self.qname = sam_row_dict["qname"]
        self.flag = int(sam_row_dict["flag"])
        self.seq = sam_row_dict["seq"]
        self.cigar = sam_row_dict["cigar"]
        self.mapq = int(sam_row_dict["mapq"])
        self.qual = sam_row_dict["qual"]
        self.pos = int(sam_row_dict["pos"])
        self.mate_record = None

    def fill_mate(self, mate_record):
        self.mate_record = mate_record
        if not mate_record.mate_record:
            mate_record = self


    def get_seq_qual(self, do_pad_wrt_ref=False, do_insert_wrt_ref=False, do_mask_low_qual=False, q_cutoff=10,
                     slice_start_wrt_ref_1based=None, slice_end_wrt_ref_1based=None):
        """
        Gets the sequence for the sam record.
        :param bool do_pad_wrt_ref: Pad sequence with gaps with respect to the reference.
                        If slice_start_wrt_ref and slice_end_wrt_ref are valid, then pads the slice with respect to the reference.
        :param bool do_insert_wrt_ref: Include insertions with respect to the reference.
                        If slice_start_wrt_ref and slice_end_wrt_ref are valid, then only includes inserts inside the slice.
        :param bool do_mask_low_qual: Mask bases with quality < q_cutoff with "N"
        :param int q_cutoff:  quality cutoff
        :param int slice_start_wrt_ref_1based:  If None, then whole sequence returned.   Otherwise, the slice 1-based start position with respect to the reference.
        :param int slice_end_wrt_ref_1based:  If None, then whole sequence returned.  Otherwise the slice end 1-based position with respect to the reference.
        :return tuple (str, str):  (sequence, quality)
        """
        # NB:  the original seq from sam file includes softclips.  Remove them with apply_cigar()

        if not self.nopad_noinsert_seq or not self.nopad_noinsert_qual:
            self.__parse_cigar()

        result_seq = self.nopad_noinsert_seq
        result_qual = self.nopad_noinsert_qual

        # Modify the slice start so that it starts at or after the sequence start
        if slice_start_wrt_ref_1based is not None:
            slice_start_wrt_ref_1based = max(self.get_seq_start_wrt_ref(), slice_start_wrt_ref_1based,)
        else:
            slice_start_wrt_ref_1based = self.get_seq_start_wrt_ref()

        # Modify the slice end so that it ends at or before the sequence end
        if slice_end_wrt_ref_1based is not None:
            slice_end_wrt_ref_1based = min(self.get_seq_end_wrt_ref(), slice_end_wrt_ref_1based,)
        else:
            slice_end_wrt_ref_1based = self.get_seq_end_wrt_ref()

        # Slice
        # 0-based start position of slice wrt result_seq
        slice_start_wrt_result_seq_0based = slice_start_wrt_ref_1based - self.get_seq_start_wrt_ref()
        # 0-based end position of slice wrt result_seq
        slice_end_wrt_result_seq_0based = len(result_seq) - 1 - (self.get_seq_end_wrt_ref() - slice_end_wrt_ref_1based )
        result_seq = result_seq[slice_start_wrt_result_seq_0based:slice_end_wrt_result_seq_0based+1]
        result_qual = result_qual[slice_start_wrt_result_seq_0based:slice_end_wrt_result_seq_0based+1]

        # Mask
        if do_mask_low_qual:
            masked_seq = ""
            for i, base in enumerate(result_seq):
                base_qual = ord(result_qual[i])-PHRED_SANGER_OFFSET
                if base != SEQ_PAD_CHAR and base_qual < q_cutoff:
                    masked_seq += "N"
                else:
                    masked_seq += base
            result_seq = masked_seq

        # Add Insertions
        if do_insert_wrt_ref:
            total_inserts = 0
            result_seq_with_inserts = ""
            result_qual_with_inserts = ""
            last_insert_pos_0based_wrt_result_seq = -1  # 0-based position wrt result_seq before the previous insertion
            # insert_pos_wrt_ref: 1-based reference position before the insertion
            for insert_1based_pos_wrt_ref, (insert_seq, insert_qual) in self.ref_pos_to_insert_seq_qual.iteritems():
                if slice_start_wrt_ref_1based <= insert_1based_pos_wrt_ref < slice_end_wrt_ref_1based:
                    total_inserts += 1
                    # insert_pos_0based_wrt_result_seq:  0-based position wrt result_seq right before the insertion
                    insert_pos_0based_wrt_result_seq =  insert_1based_pos_wrt_ref - slice_start_wrt_ref_1based

                    if do_mask_low_qual:
                        masked_insert_seq = ""
                        for i, ichar in enumerate(insert_seq):
                            iqual = ord(insert_qual[i])-PHRED_SANGER_OFFSET
                            if iqual >= q_cutoff:  # Only include inserts with high quality
                                masked_insert_seq += ichar
                    else:
                        masked_insert_seq = insert_seq

                    result_seq_with_inserts += result_seq[last_insert_pos_0based_wrt_result_seq+1:insert_pos_0based_wrt_result_seq+1] + masked_insert_seq
                    result_qual_with_inserts += result_qual[last_insert_pos_0based_wrt_result_seq+1:insert_pos_0based_wrt_result_seq+1] + insert_qual
                    last_insert_pos_0based_wrt_result_seq = insert_pos_0based_wrt_result_seq

            # TODO:  assume that bowtie will not let inserts at beginning/end of align, but check
            result_seq_with_inserts += result_seq[last_insert_pos_0based_wrt_result_seq+1:len(result_seq)]
            result_qual_with_inserts += result_qual[last_insert_pos_0based_wrt_result_seq+1:len(result_qual)]

            LOGGER.debug("qname=" + self.qname + " total_insert_1mate_only=0" +
                         " total_nonconflict_inserts=0" +
                         " total_conflict_inserts=0" +
                         " total_inserts=" + str(total_inserts))
            result_seq = result_seq_with_inserts
            result_qual = result_qual_with_inserts

        # Pad
        if do_pad_wrt_ref:
            slice_len = slice_end_wrt_ref_1based - slice_start_wrt_ref_1based + 1
            left_pad_len = slice_start_wrt_ref_1based  - 1
            right_pad_len = self.ref_len - left_pad_len - slice_len
            padded_seq = (SEQ_PAD_CHAR * left_pad_len) + self.nopad_noinsert_seq + (SEQ_PAD_CHAR * right_pad_len)
            padded_qual = (QUAL_PAD_CHAR * left_pad_len) + self.nopad_noinsert_seq + (QUAL_PAD_CHAR * right_pad_len)

            result_seq = padded_seq
            result_qual = padded_qual

        return result_seq, result_qual


    def get_insert_dict(self):
        if not self.ref_pos_to_insert_seq_qual:
            self.__parse_cigar()
        return self.ref_pos_to_insert_seq_qual



    def get_seq_start_wrt_ref(self):
        """
        Gets the 1-based start position with respect to the reference of the unclipped portion of the sequence.
        :return:
        """
        return self.pos


    def get_seq_end_wrt_ref(self):
        """
        Gets the 1-based end position with respect to the reference of the unclipped portion of the sequence.
        :return:
        """
        if not self.seq_end_wrt_ref:
            self.seq_end_wrt_ref =  self.pos + self.get_ref_align_len() - 1
        return self.seq_end_wrt_ref


    def __parse_cigar(self):
        self.nopad_noinsert_seq = ''
        self.nopad_noinsert_qual = ''
        self.ref_pos_to_insert_seq_qual = {}
        self.ref_align_len = 0
        self.seq_align_len = 0
        tokens = CIGAR_RE.findall(self.cigar)

        # Account for removing soft clipped bases on left
        shift = 0
        if tokens[0].endswith('S'):
            shift = int(tokens[0][:-1])
        pos_wrt_seq_0based = 0  # position wrt sequence
        pos_wrt_ref_1based = self.pos  # position wrt
        for token in tokens:
            length = int(token[:-1])
            # Matching sequence: carry it over
            if token[-1] == 'M' or token[-1] == 'X' or token[-1] == '=':
                self.nopad_noinsert_seq += self.seq[pos_wrt_seq_0based:(pos_wrt_seq_0based+length)]
                self.nopad_noinsert_qual += self.qual[pos_wrt_seq_0based:(pos_wrt_seq_0based+length)]
                pos_wrt_seq_0based += length
                pos_wrt_ref_1based += length
                self.ref_align_len += length
                self.seq_align_len += length
            # Deletion relative to reference: pad with gaps
            elif token[-1] == 'D' or token[-1] == 'P' or token[-1] == 'N':
                self.nopad_noinsert_seq += SEQ_PAD_CHAR*length
                self.nopad_noinsert_qual += QUAL_PAD_CHAR*length  # Assign fake placeholder score (Q=-1)
                self.ref_align_len += length
            # Insertion relative to reference: skip it (excise it)
            elif token[-1] == 'I':
                self.ref_pos_to_insert_seq_qual.update({pos_wrt_ref_1based-1:
                                                            (self.seq[pos_wrt_seq_0based:(pos_wrt_seq_0based+length)],
                                                             self.qual[pos_wrt_seq_0based:(pos_wrt_seq_0based+length)])})
                pos_wrt_seq_0based += length
                self.seq_align_len += length
            # Soft clipping leaves the sequence in the SAM - so we should skip it
            elif token[-1] == 'S':
                pos_wrt_seq_0based += length
            else:
                raise ValueError("Unable to handle CIGAR token: {} - quitting".format(token))
                sys.exit()


    def get_ref_align_len(self):
        """
        Returns the length of the alignment with respect to the reference.
        Each inserted base with respect to the reference counts as 0.  Each deleted base with respect to the reference counts as 1.
        :return:
        """
        if not self.ref_align_len:
            self.__parse_cigar()
        return self.ref_align_len

    def get_seq_align_len(self):
        """
        Returns the length of the alignment with respect to the read.
        Each deleted base with respect to the reference counts as 0.  Each inserted base with respect to the reference counts as 1.
        :return:
        """
        if not self.seq_align_len:
            self.__parse_cigar()
        return self.seq_align_len
