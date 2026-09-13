import { FunctionTool, LlmAgent } from '@google/adk';
import { z } from 'zod';

const MODEL = 'gemini-3.7-flash';

/* Mock tool implementation */
const getWeather = new FunctionTool({
  name: 'get_weather',
  description: 'Returns the current weather in a specified city.',
  parameters: z.object({
    city: z.string().describe("The name of the city for which to retrieve the weather."),
  }),
  execute: ({ city }) => {
    return { status: 'success', report: `The weather in ${city} is sunny with a temperature of 72°F` };
  },
});

export const rootAgent = new LlmAgent({
  name: '{{cookiecutter.root_agent_name}}',
  model: MODEL,
  description: 'Tells the current weather in a specified city.',
  instruction: `You are a helpful assistant that tells the current weather in a city.
                Use the 'getWeather' tool for this purpose.`,
  tools: [getWeather],
});
