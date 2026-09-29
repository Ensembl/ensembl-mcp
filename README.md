# Ensembl MCP

An Ensembl server for the **Model Context Protocol (MCP)**, which allows AI applications to discover and use tools for accessing Ensembl data.

This pilot supports the development and evaluation of the [EMBL-EBI MCP guidelines](https://github.com/EMBL-EBI-ABC/ebi-mcp-guidelines).

## Status

Early development. This repository is not yet a production service.

A Kubernetes development environment is available for the pilot. Deployment instructions and client connection details will be added once the first implementation is running.

## Aims

- Provide a small set of useful tools for accessing Ensembl data.
- Test the proposed EMBL-EBI conventions against a working implementation.
- Evaluate correctness, completeness and performance using representative tasks with trusted expected results.
- Develop a reusable reference implementation maintained by Ensembl.

## Initial approach

The planned implementation uses Python and FastMCP, following the working group's agreed reference approach.

Development will begin with one tool that retrieves Ensembl data. The first milestone is to deploy it in the development environment and complete a known task through an MCP client.

The initial tool set and underlying Ensembl APIs remain to be selected.

## Evaluation

The pilot will assess three aspects separately:

- **Protocol behaviour:** whether the server and its tools behave as expected.
- **Service performance:** response times, errors and load on upstream services.
- **Agent task success:** whether an AI application completes a task correctly and returns the required evidence.

Each evaluation task will have expected results and acceptance criteria defined before execution.

## Development

Setup, testing and deployment instructions will be added alongside the implementation.

Keep credentials and deployment secrets outside the repository.

## Licence

[Apache License 2.0](LICENSE).
