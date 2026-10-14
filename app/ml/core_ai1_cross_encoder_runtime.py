"""Optional real multi-task Cross-Encoder runtime; local files only."""
import importlib.util,json,random
from pathlib import Path
from app.models.core_ai_backend_contracts import BackendError

INPUT_TEMPLATE_VERSION="core-ai1-input-v1"
def compose_input(sample):
    return "\n".join((f"[PAPER] {sample.get('paper_identifier','')}",f"[PART] {sample.get('part_identifier','')}",f"[TASK] {sample.get('question_text','')}",f"[SCHEME] {sample.get('marking_scheme_text','')}",f"[MAX_MARK] {sample.get('maximum_score','')}",f"[PART3_QUESTION] {sample.get('selected_part3_question') or ''}",f"[STUDENT_ANSWER] {sample.get('effective_student_answer','')}"))

class TransformersMultiTaskRuntime:
    runtime_name="transformers_multitask"
    def inspect(self): return {"available":all(importlib.util.find_spec(x) for x in ("torch","transformers")),"runtime":self.runtime_name}
    def train(self,dataset_folder,output_folder,config,progress,cancellation_token):
        if not self.inspect()["available"]: raise BackendError("transformer_runtime_unavailable","PyTorch and Transformers optional dependencies are required.")
        base=Path(config.local_base_model_path)
        if not base.exists(): raise BackendError("base_model_missing","Configured local base Transformer does not exist.")
        import torch
        from torch import nn
        from torch.utils.data import DataLoader,Dataset
        from transformers import AutoModel,AutoTokenizer
        torch.manual_seed(config.seed); random.seed(config.seed)
        samples=[json.loads(line) for line in (Path(dataset_folder)/"samples.jsonl").read_text(encoding="utf-8").splitlines() if line]
        split=json.loads((Path(dataset_folder)/"splits.json").read_text()); mapping=json.loads((Path(dataset_folder)/"category_mapping.json").read_text())["mapping"]
        if len(mapping)<2: raise BackendError("category_count_invalid","Multi-task classification requires at least two categories.")
        tokenizer=AutoTokenizer.from_pretrained(str(base),local_files_only=True); encoder=AutoModel.from_pretrained(str(base),local_files_only=True)
        hidden=encoder.config.hidden_size
        class Model(nn.Module):
            def __init__(self): super().__init__(); self.encoder=encoder; self.dropout=nn.Dropout(config.dropout); self.score=nn.Linear(hidden,1); self.category=nn.Linear(hidden,len(mapping))
            def forward(self,**batch):
                pooled=self.encoder(input_ids=batch["input_ids"],attention_mask=batch["attention_mask"]).last_hidden_state[:,0]; pooled=self.dropout(pooled); return self.score(pooled).squeeze(-1),self.category(pooled)
        model=Model(); device="cuda" if config.device=="auto" and torch.cuda.is_available() else ("cpu" if config.device=="auto" else config.device); model.to(device)
        truncations=0
        class Rows(Dataset):
            def __init__(self,rows): self.rows=rows
            def __len__(self): return len(self.rows)
            def __getitem__(self,index):
                nonlocal truncations
                row=self.rows[index]; text=compose_input(row); full=tokenizer(text,truncation=False); truncations+=int(len(full["input_ids"])>config.max_sequence_length)
                encoded=tokenizer(text,truncation=True,max_length=config.max_sequence_length,padding="max_length",return_tensors="pt")
                return encoded["input_ids"].squeeze(0),encoded["attention_mask"].squeeze(0),torch.tensor(row["normalized_score"],dtype=torch.float),torch.tensor(row["category_id"],dtype=torch.long)
        train_rows=[s for s in samples if split["assignments"].get(s["sample_id"])=="train"]; val_rows=[s for s in samples if split["assignments"].get(s["sample_id"])=="validation"]
        if not train_rows or not val_rows: raise BackendError("training_split_empty","Train and validation samples are required.")
        loader=DataLoader(Rows(train_rows),batch_size=config.batch_size,shuffle=True); optimizer=torch.optim.AdamW(model.parameters(),lr=config.learning_rate,weight_decay=config.weight_decay); mse=nn.MSELoss(); ce=nn.CrossEntropyLoss(); losses=[]
        model.train()
        for epoch in range(config.epochs):
            optimizer.zero_grad()
            for step,(ids,mask,scores,categories) in enumerate(loader,1):
                cancellation_token.raise_if_cancelled(); predicted,logits=model(input_ids=ids.to(device),attention_mask=mask.to(device)); loss=config.regression_loss_weight*mse(predicted,scores.to(device))+config.classification_loss_weight*ce(logits,categories.to(device)); loss.backward()
                if step%config.gradient_accumulation==0 or step==len(loader): optimizer.step(); optimizer.zero_grad()
                losses.append(float(loss.detach().cpu())); progress(f"Epoch {epoch+1}/{config.epochs}",100*(epoch+step/len(loader))/config.epochs,epoch+1)
        destination=Path(output_folder); encoder_dir=destination/"encoder"; tokenizer_dir=destination/"tokenizer"; model.encoder.save_pretrained(encoder_dir); tokenizer.save_pretrained(tokenizer_dir); torch.save({"score_head":model.score.state_dict(),"category_head":model.category.state_dict()},destination/"heads.pt")
        return {"artifacts":[encoder_dir,tokenizer_dir,destination/"heads.pt"],"training_metrics":{"training_combined_loss":sum(losses)/len(losses),"validation_support":len(val_rows)},"truncation_count":truncations,"runtime":{"device":device,"torch":torch.__version__}}
