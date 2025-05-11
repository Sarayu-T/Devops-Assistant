


import os
import chromadb
import tempfile
import git
import glob
from pathlib import Path
from typing import List, Dict, Any
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import torch
import requests
import json
import shutil

# Step 1: Define helper functions for code parsing and storage


def clone_github_repo(repo_url: str, local_path: str) -> str:
    """Clone a GitHub repository to a local path, cleaning the directory if it already exists."""
    print(f"Cloning repository {repo_url} to {local_path}...")

    # Clean the directory if it exists
    if os.path.exists(local_path):
        print(f"Directory {local_path} already exists. Removing it...")
        shutil.rmtree(local_path)

    try:
        git.Repo.clone_from(repo_url, local_path)
        print("Repository cloned successfully.")
        return local_path
    except git.GitCommandError as e:
        print(f"Error cloning repository: {e}")
        raise


def get_file_contents(repo_path: str, file_extensions: List[str] = None) -> List[Dict[str, Any]]:
    """
    Extract content from files in the repository, optionally filtering by extension.
    Returns a list of dictionaries with file paths and contents.
    """
    if file_extensions is None:
        # Default to common code file extensions
        file_extensions = ['.py', '.js', '.java', '.cpp', '.c', '.h', '.hpp', '.cs', '.go', '.rb', '.php', '.ts', '.html', '.css']

    all_files = []
    # Walk through the repository
    for root, _, files in os.walk(repo_path):
        # Skip hidden folders like .git
        if any(part.startswith('.') for part in Path(root).parts):
            continue

        for file in files:
            file_path = os.path.join(root, file)
            # Check if the file has one of the desired extensions
            if any(file.endswith(ext) for ext in file_extensions):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    # Calculate relative path from repo_path
                    rel_path = os.path.relpath(file_path, repo_path)
                    all_files.append({
                        "path": rel_path,
                        "content": content
                    })
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")

    print(f"Extracted content from {len(all_files)} files.")
    return all_files

def split_code_into_chunks(file_contents: List[Dict[str, Any]], chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Split code files into smaller chunks for better vector storage and retrieval.
    Each chunk keeps reference to its original file.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )

    chunks = []
    for file_info in file_contents:
        file_path = file_info["path"]
        content = file_info["content"]

        # Split the content into chunks
        content_chunks = text_splitter.split_text(content)

        # Create a document for each chunk
        for i, chunk in enumerate(content_chunks):
            chunks.append({
                "path": file_path,
                "chunk_id": f"{file_path}_chunk_{i}",
                "content": chunk,
                "metadata": {
                    "path": file_path,
                    "chunk_number": i,
                    "total_chunks": len(content_chunks)
                }
            })

    print(f"Split {len(file_contents)} files into {len(chunks)} chunks.")
    return chunks

# Step 2: Set up embedding model and vector storage

class CodeEmbeddingSystem:
    def __init__(self, persist_directory: str = "./chroma_db"):
        """Initialize the embedding system with HuggingFace and ChromaDB."""
        self.persist_directory = persist_directory

        # Initialize the embedding model (free alternative to OpenAI)
        print("Loading embedding model...")
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

        # Initialize ChromaDB (free alternative to Pinecone)
        print("Initializing ChromaDB...")
        self.chroma_client = chromadb.PersistentClient(path=persist_directory)

        # Create or get the collection
        self.collection = self.chroma_client.get_or_create_collection(
            name="code_repository",
            metadata={"hnsw:space": "cosine"}
        )

        print("Embedding system initialized.")

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of text strings."""
        embeddings = self.embedding_model.encode(texts)
        return embeddings.tolist()

    def add_chunks_to_db(self, chunks: List[Dict[str, Any]]) -> None:
        """Add code chunks to the vector database."""
        if not chunks:
            print("No chunks to add to the database.")
            return

        # Prepare data for ChromaDB
        ids = [chunk["chunk_id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        metadatas = [chunk["metadata"] for chunk in chunks]

        # Generate embeddings
        embeddings = self.generate_embeddings(documents)

        # Add to ChromaDB
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

        print(f"Added {len(chunks)} chunks to the vector database.")

    def query_similar_code(self, error_message: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Query the vector database for code similar to the error message."""
        # Generate embedding for the error message
        error_embedding = self.generate_embeddings([error_message])[0]

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[error_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )

        # Format results
        formatted_results = []
        for i in range(len(results["ids"][0])):
            formatted_results.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity": 1 - results["distances"][0][i]  # Convert distance to similarity
            })

        return formatted_results

# Step 3: LLM integration for error analysis and fix generation using Gemini API
class ErrorAnalysisSystem:
    def __init__(self, api_key: str = None):
        """
        Initialize the error analysis system with OpenRouter DeepSeek prover API .

        Args:
            api_key (str): Your Gemini API key. Required for generating fixes.
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("You will need to provide an API key before generating fixes.")


    def generate_fix(self, error_message: str, code_contexts: List[Dict[str, Any]]) -> str:
        """Generate a fix for the error using the DeepSeek API."""
        if not self.api_key:
            return "ERROR: No Gemini API key provided. Please set the API key before generating fixes."
        
        # Prepare the context with error and code
        context_text = "\n\n".join([
            f"File: {context['metadata']['path']}\n\n{context['content']}\n"
            for context in code_contexts[:3]  # Limit to top 3 results for brevity
        ])

        prompt = f"""
        You are an expert programmer. Given the following error message and relevant code from a repository,
        identify the likely cause of the error and suggest a fix showing whole code.

        ERROR MESSAGE:
        {error_message}

        RELEVANT CODE CONTEXT:
        {context_text}

        Please analyze the error and provide:
        1. The root cause of the error
        2. A specific fix for the error
        3. Any additional context or explanation about why this fix works

        Your solution should be clear, concise, and directly address the error.
        """

        headers = {
        "Authorization": f"Bearer {self.api_key}",
        "HTTP-Referer": "http://localhost",  # Change if you deploy
        "Content-Type": "application/json"
    }
        data = {
        "model": "deepseek/deepseek-prover-v2:free",
        "messages": [
            {"role": "system", "content": "You are a helpful AI coding assistant."},
            {"role": "user", "content": prompt}
        ]
    }
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        except Exception as e:
            return f"Error querying DeepSeek via OpenRouter: {e}"

# Step 4: Main workflow to tie everything together

class GitHubErrorResolver:
    def __init__(self, deepseek_api_key: str = None):
        """
        Initialize the GitHub error resolver with necessary components.

        Args:
            gemini_api_key (str): Your Gemini API key for error analysis.
        """
        self.temp_dir = tempfile.mkdtemp()
        self.embedding_system = CodeEmbeddingSystem()
        self.error_analyzer = ErrorAnalysisSystem(api_key=deepseek_api_key)

    def process_repository(self, repo_url: str) -> None:
        """Process a GitHub repository: clone, extract code, and store in vector DB."""
        rep = "https://github.com/"+repo_url+".git"
        repo_url = rep
        print(f"Processing repository: {repo_url}")

        # Clone the repository
        repo_path = clone_github_repo(repo_url, self.temp_dir)

        # Extract content from files
        file_contents = get_file_contents(repo_path)

        # Split into chunks
        chunks = split_code_into_chunks(file_contents)

        # Add to vector DB
        self.embedding_system.add_chunks_to_db(chunks)

        #print(f"Repository {repo_url} processed and stored in vector database.")

    def get_failed_path(self,error_message:str) ->str:
        similar_code = self.embedding_system.query_similar_code(error_message)

        if not similar_code:
            return "No relevant code found for this error."
        if similar_code:
            return similar_code[0].get("metadata",{}).get("path","")

    def resolve_error(self, error_message: str) -> Dict[str, Any]:
        """Resolve an error by finding relevant code and generating a structured fix."""
        similar_code = self.embedding_system.query_similar_code(error_message)

        if not similar_code:
            return {
                "error_type": None,
                "error_message": "No relevant code found.",
                "line_number": None,
                "suggested_fix": None,
                "explanation": None
            }

        raw_fix = self.error_analyzer.generate_fix(error_message, similar_code)

        try:
            fix_data = json.loads(raw_fix)
            # Ensure all expected keys are present
            expected_keys = ["error_type", "error_message", "line_number", "suggested_fix", "explanation"]
            for key in expected_keys:
                fix_data.setdefault(key, None)
            return fix_data

        except json.JSONDecodeError as e:
            print("⚠️ Failed to parse LLM output as JSON:", e)
            print("Raw LLM response:\n", raw_fix)

            # Fallback: return raw output as the suggested fix
            return {
                "error_type": None,
                "error_message": None,
                "line_number": None,
                "suggested_fix": raw_fix.strip(),
                "explanation": None
            }

# Example usage in Google Colab
def run_example():
    # Install the latest version of the Gemini SDK
    print("Installing latest Gemini SDK...")

    # Get Gemini API key (you would provide your actual key)
    gemini_api_key = input("Enter your Gemini API key: ")

    # Initialize the resolver with the API key
    resolver = GitHubErrorResolver(gemini_api_key=gemini_api_key)

    # Check available models before proceeding
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        print("\nAvailable Gemini models:")
        for m in genai.list_models():
            if "gemini" in m.name.lower():
                print(f" - {m.name}")
    except Exception as e:
        print(f"Error listing models: {e}")

    # Process a repository
    repo_url = input("Enter GitHub repository URL (or press Enter for default example): ")
    if not repo_url:
        repo_url = "https://github.com/sizzcode/build_test.git"
        print(f"Using example repository: {repo_url}")

    resolver.process_repository(repo_url)

    # Resolve an example error
    error_message = """
 File "C:\ProgramData\Jenkins\.jenkins\workspace\Testing_error\hello_world.py", line 6
    return "h
           ^
SyntaxError: unterminated string literal (detected at line 6)
    """

    # Allow custom error input
    custom_error = input("Enter your error message (or press Enter for example error): ")
    if custom_error:
        error_message = custom_error

    fix = resolver.resolve_error(error_message)
    print("\n\nGenerated Fix:")
    print(fix)

# Run a complete example in Colab
if __name__ == "__main__":
    run_example()