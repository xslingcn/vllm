"""
This file contains a new class `KVLookupBufferBase` that allows developers to 
think of KV cache operations as inserting new KV cache entries (`insert`) 
into the lookup buffer and querying existing KV caches (`drop_select`) 
from the lookup buffer.

All distributed communications are abstracted behind this class.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

import torch

from vllm.sequence import IntermediateTensors

if TYPE_CHECKING:
    from vllm.config import KVTransferConfig
    from vllm.worker.model_runner import ModelInputForGPUWithSamplingMetadata


class KVConnectorBase(ABC):
    """
    Abstract base class for a KV connector.

    This class provides an abstraction for a key-value (KV) cache lookup buffer.
    
    The key of the lookup buffer:
    - input_tokens: token IDs of the request
    - roi: a binary mask on top of input_tokens.
      - Purpose of roi: Since KV cache may only be available for a subset of 
        tokens in the input (for example, when vLLM is connected to an external 
        KV cache service), roi specifies the subset of tokens that the KV cache 
        is associated with.
      - NOTE: roi can be further extended to describe which part of KV the 
        current process is holding (each process may only hold a part of KV 
        due to TP and PP). This is not implemented for now.
        
    The value of the lookup buffer:
    - key: the key tensor in the KV cache
    - value: the value tensor in the KV cache
    - hidden: the final hidden state generated by model forwarding. This allows 
      vLLM to bypass further model forwarding by transmitting the hidden state.
    """

    @abstractmethod
    def __init__(
        self,
        rank: int,
        local_rank: int,
        config: "KVTransferConfig",
    ):
        raise NotImplementedError

    @abstractmethod
    def insert(self, input_tokens: torch.Tensor, roi: torch.Tensor,
               key: torch.Tensor, value: torch.Tensor,
               hidden: torch.Tensor) -> None:
        """Insert into the lookup buffer, similar to SQL insert
        
        The functionality is similar to the following python statement
        ```
        connector[input_tokens, roi] = [key, value, hidden]
        ```
        
        FIXME: in the future, we should only have two arguments, key and value,
        where key is a tensor dict and value is a tensor dict.
        
        FIXME: we should transmit both sampler outputs and the hidden states.

        Args:
            input_tokens (torch.Tensor): token IDs.
            roi (torch.Tensor): A binary mask on top of the input tokens
            key (torch.Tensor): The key tensor in the KV cache.
            value (torch.Tensor): The value tensor in the KV cache.
            hidden (torch.Tensor): The final hidden state tensor generated 
                                   during model forwarding to bypass model 
                                   forwarding.

        Raises:
            NotImplementedError: This method must be implemented in subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def select(self, input_tokens: Optional[torch.Tensor],
               roi: Optional[torch.Tensor]) -> List[Optional[torch.Tensor]]:
        """Select KV cache entries from the connector.
        
        The functionality is similar to the following python statements
        ```
        return connector[input_tokens, roi]
        ```
        
        If `input_tokens` and `roi` is `None`, it means selecting any of the
        KV caches in the buffer, return, and remove it from the buffer, useful
        when offloading KV cache to KV cache storage service.

        Args:
            input_tokens (torch.Tensor): token IDs.
            roi (torch.Tensor): A binary mask on top of the input tokens

        Returns:
            List[Optional[torch.Tensor]]: A list of tensors. Can be None.

        Raises:
            NotImplementedError: This method must be implemented in subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the buffer and release resources.

        This method is responsible for cleaning up resources related to the 
        connector when it is no longer needed.

        Raises:
            NotImplementedError: This method must be implemented in subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    def send_kv_caches_and_hidden_states(
        self,
        model_executable: torch.nn.Module,
        model_input: "ModelInputForGPUWithSamplingMetadata",
        kv_caches: List[torch.Tensor],
        hidden_or_intermediate_states: Union[torch.Tensor,
                                             IntermediateTensors],
    ) -> None:
        """
        Send KV caches and hidden states to the connector.

        This method processes the input tokens, KV caches, and 
        hidden/intermediate states for a given model and sends the data to the 
        decode instance.

        Args:
            model_executable (torch.nn.Module): The model executable containing 
                start and end layer information.
            model_input (ModelInputForGPUWithSamplingMetadata): The input
                metadata from vLLM.
            kv_caches (List[torch.Tensor]): List of KV caches (keys and values) 
                for each layer.
            hidden_or_intermediate_states (Union[torch.Tensor, 
            IntermediateTensors]): 
                The hidden or intermediate states associated with the tokens.

        Returns:
            None

        """

        raise NotImplementedError

    @abstractmethod
    def recv_kv_caches_and_hidden_states(
        self, model_executable: torch.nn.Module,
        model_input: "ModelInputForGPUWithSamplingMetadata",
        kv_caches: List[torch.Tensor]
    ) -> Tuple[Union[torch.Tensor, IntermediateTensors], bool,
               "ModelInputForGPUWithSamplingMetadata"]:
        """
        Receive KV caches and hidden states from the connector.

        This method attempts to retrieve KV caches and hidden states for input
        tokens. If all required KV caches and hidden states are received, it
        will bypass model input, else it will fall back to normal vLLM model 
        forwarding.

        Args:
            model_executable (torch.nn.Module): 
                The model executable from vLLM modelrunner.
            model_input (ModelInputForGPUWithSamplingMetadata): 
                The model input from vLLM modelrunner.
            kv_caches (List[torch.Tensor]): 
                List of KV caches for each layer.

        Returns:
            - hidden_or_intermediate_states (torch.Tensor or
            IntermediateTensors): 
                Concatenated hidden states if all required data is retrieved, 
                otherwise `None`.
            - bypass_model_exec (bool): 
                Indicates whether the model execution can be skipped (True) or 
                needs to be redone (False).
            - model_input (ModelInputForGPUWithSamplingMetadata): 
                Optionally adjusted input metadata for re-execution when 
                `bypass_model_exec=False`.

        """

        raise NotImplementedError
