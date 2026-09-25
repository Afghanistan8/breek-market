/**
 * Every network-dependent value the app needs, in one place.
 *
 * Nothing here is baked into a component. Point the app at a different
 * deployment by changing the environment, not the code.
 */

const read = (key: string, fallback: string): string => {
  const value = import.meta.env[key as keyof ImportMetaEnv] as string | undefined;
  return value && value.length > 0 ? value : fallback;
};

export const env = {
  /** Deployed BreekForecast Intelligent Contract. */
  contract: read("VITE_BREEK_CONTRACT", "0x4aDb6a8f9D0B920cC5699F75060324575C01E19a"),
  chainId: Number(read("VITE_BREEK_CHAIN_ID", "61999")),
  rpc: read("VITE_BREEK_RPC", "https://studio.genlayer.com/api"),
  network: read("VITE_BREEK_NETWORK", "studionet"),
  /** Human-readable name shown by the wallet when it adds the network. */
  chainName: read("VITE_BREEK_CHAIN_NAME", "GenLayer Studio Network"),
  explorer: read("VITE_BREEK_EXPLORER", "https://explorer-studio.genlayer.com"),
} as const;

export const isAddress = (value: string): boolean => /^0x[0-9a-fA-F]{40}$/.test(value);

export const contractConfigured = isAddress(env.contract);

export const explorerTx = (hash: string): string => `${env.explorer}/tx/${hash}`;
export const explorerAddress = (address: string): string =>
  `${env.explorer}/address/${address}`;
