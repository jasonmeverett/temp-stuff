/** Default URLs from your deployed stack; override with Vite env in Amplify if the API changes. */
const DEPLOYED = {
  base: "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com",
  read: "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com/read",
  write: "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com/write",
};

export const telemetryApiBaseUrl =
  import.meta.env.VITE_TELEMETRY_API_URL?.replace(/\/$/, "") || DEPLOYED.base;

export const readEndpointUrl =
  import.meta.env.VITE_READ_ENDPOINT_URL || DEPLOYED.read;

export const writeEndpointUrl =
  import.meta.env.VITE_WRITE_ENDPOINT_URL || DEPLOYED.write;
