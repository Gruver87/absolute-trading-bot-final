#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ABSOLUTE BLOCKCHAIN - РљРђРЎРўРћРњРќР«Р• РРЎРљР›Р®Р§Р•РќРРЇ
рџ”ђ WATERMARK: DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
"""


class AbsoluteBlockchainError(Exception):
    """Р‘Р°Р·РѕРІРѕРµ РёСЃРєР»СЋС‡РµРЅРёРµ РґР»СЏ РІСЃРµРіРѕ Р±Р»РѕРєС‡РµР№РЅР°"""
    pass


# ============================================================================
# РћРЁРР‘РљР Р‘Р›РћРљР§Р•Р™РќРђ
# ============================================================================

class BlockchainError(AbsoluteBlockchainError):
    """РћР±С‰Р°СЏ РѕС€РёР±РєР° Р±Р»РѕРєС‡РµР№РЅР°"""
    pass


class BlockNotFoundError(BlockchainError):
    """Р‘Р»РѕРє РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class TransactionNotFoundError(BlockchainError):
    """РўСЂР°РЅР·Р°РєС†РёСЏ РЅРµ РЅР°Р№РґРµРЅР°"""
    pass


class InvalidBlockError(BlockchainError):
    """РќРµРІРµСЂРЅС‹Р№ Р±Р»РѕРє"""
    pass


class InvalidTransactionError(BlockchainError):
    """РќРµРІРµСЂРЅР°СЏ С‚СЂР°РЅР·Р°РєС†РёСЏ"""
    pass


class ChainReorgError(BlockchainError):
    """Р РµРѕСЂРіР°РЅРёР·Р°С†РёСЏ С†РµРїРѕС‡РєРё"""
    pass


# ============================================================================
# РћРЁРР‘РљР РљРћРЁР•Р›Р¬РљРђ
# ============================================================================

class WalletError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° РєРѕС€РµР»СЊРєР°"""
    pass


class InsufficientBalanceError(WalletError):
    """РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ"""
    pass


class InvalidAddressError(WalletError):
    """РќРµРІРµСЂРЅС‹Р№ Р°РґСЂРµСЃ"""
    pass


class InvalidPrivateKeyError(WalletError):
    """РќРµРІРµСЂРЅС‹Р№ РїСЂРёРІР°С‚РЅС‹Р№ РєР»СЋС‡"""
    pass


class InvalidMnemonicError(WalletError):
    """РќРµРІРµСЂРЅР°СЏ РјРЅРµРјРѕРЅРёС‡РµСЃРєР°СЏ С„СЂР°Р·Р°"""
    pass


class WalletNotFoundError(WalletError):
    """РљРѕС€РµР»РµРє РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class NonceError(WalletError):
    """РћС€РёР±РєР° nonce"""
    pass


# ============================================================================
# РћРЁРР‘РљР РљР РРџРўРћР“Р РђР¤РР
# ============================================================================

class CryptoError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° РєСЂРёРїС‚РѕРіСЂР°С„РёРё"""
    pass


class SignatureVerificationError(CryptoError):
    """РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё РїРѕРґРїРёСЃРё"""
    pass


class KeyGenerationError(CryptoError):
    """РћС€РёР±РєР° РіРµРЅРµСЂР°С†РёРё РєР»СЋС‡РµР№"""
    pass


# ============================================================================
# РћРЁРР‘РљР РЎР•РўР
# ============================================================================

class NetworkError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° СЃРµС‚Рё"""
    pass


class PeerConnectionError(NetworkError):
    """РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ Рє РїРёСЂСѓ"""
    pass


class SyncError(NetworkError):
    """РћС€РёР±РєР° СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёРё"""
    pass


class TimeoutError(NetworkError):
    """РўР°Р№РјР°СѓС‚"""
    pass


# ============================================================================
# РћРЁРР‘РљР РњРђР™РќРРќР“Рђ
# ============================================================================

class MiningError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° РјР°Р№РЅРёРЅРіР°"""
    pass


class EmissionLimitError(MiningError):
    """Р›РёРјРёС‚ СЌРјРёСЃСЃРёРё РїСЂРµРІС‹С€РµРЅ"""
    pass


class DifficultyError(MiningError):
    """РћС€РёР±РєР° СЃР»РѕР¶РЅРѕСЃС‚Рё"""
    pass


# ============================================================================
# РћРЁРР‘РљР РЎРњРђР Рў-РљРћРќРўР РђРљРўРћР’
# ============================================================================

class ContractError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° СЃРјР°СЂС‚-РєРѕРЅС‚СЂР°РєС‚Р°"""
    pass


class ContractNotFoundError(ContractError):
    """РљРѕРЅС‚СЂР°РєС‚ РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class ContractExecutionError(ContractError):
    """РћС€РёР±РєР° РІС‹РїРѕР»РЅРµРЅРёСЏ РєРѕРЅС‚СЂР°РєС‚Р°"""
    pass


class OutOfGasError(ContractError):
    """РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РіР°Р·Р°"""
    pass


class RevertError(ContractError):
    """РћС‚РєР°С‚ С‚СЂР°РЅР·Р°РєС†РёРё"""
    pass


# ============================================================================
# РћРЁРР‘РљР DEX
# ============================================================================

class DEXError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° DEX"""
    pass


class PairNotFoundError(DEXError):
    """РўРѕСЂРіРѕРІР°СЏ РїР°СЂР° РЅРµ РЅР°Р№РґРµРЅР°"""
    pass


class InsufficientLiquidityError(DEXError):
    """РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ Р»РёРєРІРёРґРЅРѕСЃС‚Рё"""
    pass


class SlippageError(DEXError):
    """РџСЂРѕСЃРєР°Р»СЊР·С‹РІР°РЅРёРµ РїСЂРµРІС‹С€РµРЅРѕ"""
    pass


# ============================================================================
# РћРЁРР‘РљР РЎРўР•Р™РљРРќР“Рђ
# ============================================================================

class StakingError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° СЃС‚РµР№РєРёРЅРіР°"""
    pass


class StakeNotFoundError(StakingError):
    """РЎС‚РµР№Рє РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class LockPeriodError(StakingError):
    """РћС€РёР±РєР° РїРµСЂРёРѕРґР° Р±Р»РѕРєРёСЂРѕРІРєРё"""
    pass


# ============================================================================
# РћРЁРР‘РљР GOVERNANCE
# ============================================================================

class GovernanceError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° СѓРїСЂР°РІР»РµРЅРёСЏ"""
    pass


class ProposalNotFoundError(GovernanceError):
    """РџСЂРµРґР»РѕР¶РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ"""
    pass


class AlreadyVotedError(GovernanceError):
    """РЈР¶Рµ РїСЂРѕРіРѕР»РѕСЃРѕРІР°РЅРѕ"""
    pass


class QuorumNotMetError(GovernanceError):
    """РљРІРѕСЂСѓРј РЅРµ РґРѕСЃС‚РёРіРЅСѓС‚"""
    pass


# ============================================================================
# РћРЁРР‘РљР NFT
# ============================================================================

class NFTError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° NFT"""
    pass


class NFTNotFoundError(NFTError):
    """NFT РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class NotOwnerError(NFTError):
    """РќРµ СЏРІР»СЏРµС‚СЃСЏ РІР»Р°РґРµР»СЊС†РµРј"""
    pass


# ============================================================================
# РћРЁРР‘РљР РљР РћРЎРЎ-Р§Р•Р™Рќ
# ============================================================================

class BridgeError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° РјРѕСЃС‚Р°"""
    pass


class ChainNotSupportedError(BridgeError):
    """Р¦РµРїСЊ РЅРµ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ"""
    pass


class BridgeTransferError(BridgeError):
    """РћС€РёР±РєР° РєСЂРѕСЃСЃ-С‡РµР№РЅ РїРµСЂРµРІРѕРґР°"""
    pass


# ============================================================================
# РћРЁРР‘РљР ZK PRIVACY
# ============================================================================

class ZKError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° ZK РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІ"""
    pass


class InvalidProofError(ZKError):
    """РќРµРІРµСЂРЅРѕРµ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ"""
    pass


class NullifierAlreadyUsedError(ZKError):
    """Nullifier СѓР¶Рµ РёСЃРїРѕР»СЊР·РѕРІР°РЅ"""
    pass


class CommitmentNotFoundError(ZKError):
    """Commitment РЅРµ РЅР°Р№РґРµРЅ"""
    pass


# ============================================================================
# РћРЁРР‘РљР WASM
# ============================================================================

class WASMError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° WASM"""
    pass


class CompilationError(WASMError):
    """РћС€РёР±РєР° РєРѕРјРїРёР»СЏС†РёРё"""
    pass


class InvalidWASMError(WASMError):
    """РќРµРІРµСЂРЅС‹Р№ WASM РєРѕРґ"""
    pass


# ============================================================================
# РћРЁРР‘РљР AI CONSENSUS
# ============================================================================

class AIConsensusError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° AI РєРѕРЅСЃРµРЅСЃСѓСЃР°"""
    pass


class ModelNotFoundError(AIConsensusError):
    """РњРѕРґРµР»СЊ РЅРµ РЅР°Р№РґРµРЅР°"""
    pass


class TrainingError(AIConsensusError):
    """РћС€РёР±РєР° РѕР±СѓС‡РµРЅРёСЏ"""
    pass


class InvalidProofOfWorkError(AIConsensusError):
    """РќРµРІРµСЂРЅРѕРµ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ СЂР°Р±РѕС‚С‹"""
    pass


# ============================================================================
# РћРЁРР‘РљР РЁРђР Р”РРќР“Рђ
# ============================================================================

class ShardingError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° С€Р°СЂРґРёРЅРіР°"""
    pass


class ShardNotFoundError(ShardingError):
    """РЁР°СЂРґ РЅРµ РЅР°Р№РґРµРЅ"""
    pass


class CrossShardError(ShardingError):
    """РћС€РёР±РєР° РјРµР¶С€Р°СЂРґРѕРІРѕР№ С‚СЂР°РЅР·Р°РєС†РёРё"""
    pass


class MigrationError(ShardingError):
    """РћС€РёР±РєР° РјРёРіСЂР°С†РёРё"""
    pass


# ============================================================================
# РћРЁРР‘РљР DATA AVAILABILITY
# ============================================================================

class DataAvailabilityError(AbsoluteBlockchainError):
    """РћС€РёР±РєР° РґРѕСЃС‚СѓРїРЅРѕСЃС‚Рё РґР°РЅРЅС‹С…"""
    pass


class DataNotAvailableError(DataAvailabilityError):
    """Р”Р°РЅРЅС‹Рµ РЅРµРґРѕСЃС‚СѓРїРЅС‹"""
    pass


class SamplingError(DataAvailabilityError):
    """РћС€РёР±РєР° СЃРµРјРїР»РёСЂРѕРІР°РЅРёСЏ"""
    pass


# ============================================================================
# Р’РЎРџРћРњРћР“РђРўР•Р›Р¬РќР«Р• Р¤РЈРќРљР¦РР
# ============================================================================

def handle_exception(e: Exception, context: str = ""):
    """
    РћР±СЂР°Р±РѕС‚РєР° РёСЃРєР»СЋС‡РµРЅРёР№ СЃ РєРѕРЅС‚РµРєСЃС‚РѕРј
    """
    if isinstance(e, AbsoluteBlockchainError):
        print(f"вќЊ {context}: {e}")
    else:
        print(f"вќЊ {context}: РќРµРёР·РІРµСЃС‚РЅР°СЏ РѕС€РёР±РєР° - {e}")
    
    return {
        'success': False,
        'error': str(e),
        'type': e.__class__.__name__,
        'context': context
    }


def assert_condition(condition: bool, error: str, error_class=BlockchainError):
    """
    РџСЂРѕРІРµСЂРєР° СѓСЃР»РѕРІРёСЏ СЃ РІС‹Р±СЂРѕСЃРѕРј РёСЃРєР»СЋС‡РµРЅРёСЏ
    """
    if not condition:
        raise error_class(error)


__all__ = [
    # Р‘Р°Р·РѕРІС‹Рµ
    'AbsoluteBlockchainError',
    'BlockchainError',
    
    # Р‘Р»РѕРєС‡РµР№РЅ
    'BlockNotFoundError',
    'TransactionNotFoundError',
    'InvalidBlockError',
    'InvalidTransactionError',
    'ChainReorgError',
    
    # РљРѕС€РµР»РµРє
    'WalletError',
    'InsufficientBalanceError',
    'InvalidAddressError',
    'InvalidPrivateKeyError',
    'InvalidMnemonicError',
    'WalletNotFoundError',
    'NonceError',
    
    # РљСЂРёРїС‚РѕРіСЂР°С„РёСЏ
    'CryptoError',
    'SignatureVerificationError',
    'KeyGenerationError',
    
    # РЎРµС‚СЊ
    'NetworkError',
    'PeerConnectionError',
    'SyncError',
    'TimeoutError',
    
    # РњР°Р№РЅРёРЅРі
    'MiningError',
    'EmissionLimitError',
    'DifficultyError',
    
    # РљРѕРЅС‚СЂР°РєС‚С‹
    'ContractError',
    'ContractNotFoundError',
    'ContractExecutionError',
    'OutOfGasError',
    'RevertError',
    
    # DEX
    'DEXError',
    'PairNotFoundError',
    'InsufficientLiquidityError',
    'SlippageError',
    
    # РЎС‚РµР№РєРёРЅРі
    'StakingError',
    'StakeNotFoundError',
    'LockPeriodError',
    
    # Governance
    'GovernanceError',
    'ProposalNotFoundError',
    'AlreadyVotedError',
    'QuorumNotMetError',
    
    # NFT
    'NFTError',
    'NFTNotFoundError',
    'NotOwnerError',
    
    # РљСЂРѕСЃСЃ-С‡РµР№РЅ
    'BridgeError',
    'ChainNotSupportedError',
    'BridgeTransferError',
    
    # ZK Privacy
    'ZKError',
    'InvalidProofError',
    'NullifierAlreadyUsedError',
    'CommitmentNotFoundError',
    
    # WASM
    'WASMError',
    'CompilationError',
    'InvalidWASMError',
    
    # AI Consensus
    'AIConsensusError',
    'ModelNotFoundError',
    'TrainingError',
    'InvalidProofOfWorkError',
    
    # РЁР°СЂРґРёРЅРі
    'ShardingError',
    'ShardNotFoundError',
    'CrossShardError',
    'MigrationError',
    
    # Data Availability
    'DataAvailabilityError',
    'DataNotAvailableError',
    'SamplingError',
    
    # Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ
    'handle_exception',
    'assert_condition'
]