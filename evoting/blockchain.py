import hashlib
import time
import json

from evoting.config import SECRET_SALT, CANDIDATES


class Block:
    def __init__(self, index, npm, vote, prev_hash, timestamp=None):
        self.index = index
        self.timestamp = timestamp or time.time()
        self.npm = npm
        self.vote = vote
        self.prev_hash = prev_hash
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "npm": self.npm,
            "vote": self.vote,
            "prev_hash": self.prev_hash
        }, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "npm": self.npm,
            "vote": self.vote,
            "prev_hash": self.prev_hash,
            "hash": self.hash
        }

class Blockchain:
    def __init__(self):
        self.chain = []
        # Create genesis block
        self.create_block(npm="GENESIS", vote="N/A", prev_hash="0")

    def create_block(self, npm, vote, prev_hash):
        index = len(self.chain)
        block = Block(index, npm, vote, prev_hash)
        self.chain.append(block)
        return block

    def get_latest_block(self):
        return self.chain[-1]

    @staticmethod
    def _hash_npm(npm):
        """Hash NPM dengan Secret Salt untuk anonimitas pada ledger."""
        return hashlib.sha256(f"{npm}{SECRET_SALT}".encode()).hexdigest()

    def has_voted(self, npm):
        """True bila hash NPM sudah pernah tercatat di blockchain (cegah vote ganda)."""
        hashed_npm = self._hash_npm(npm)
        return any(block.npm == hashed_npm for block in self.chain[1:])

    def add_vote(self, npm, vote):
        # Hash NPM with a Secret Salt for maximum anonymity
        # This prevents de-anonymization even if the hacker knows the student NPM list
        hashed_npm = self._hash_npm(npm)

        prev_hash = self.get_latest_block().hash
        return self.create_block(npm=hashed_npm, vote=vote, prev_hash=prev_hash)

    def get_invalid_blocks(self):
        """Returns a list of indices of blocks that have been tampered with."""
        invalid_indices = []
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            prev_block = self.chain[i-1]

            # Check if current block data matches its hash
            if current_block.hash != current_block.calculate_hash():
                invalid_indices.append(current_block.index)
            
            # Check if the chain link is broken
            if current_block.prev_hash != prev_block.hash:
                if current_block.index not in invalid_indices:
                    invalid_indices.append(current_block.index)
        return invalid_indices

    def is_chain_valid(self):
        return len(self.get_invalid_blocks()) == 0

    def get_results(self):
        results = {c: 0 for c in CANDIDATES}
        for block in self.chain[1:]:
            if block.vote in results:
                results[block.vote] += 1
        return results
