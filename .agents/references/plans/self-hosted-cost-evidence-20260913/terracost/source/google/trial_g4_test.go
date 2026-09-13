package google_test
import("context";"encoding/json";"net/http";"net/http/httptest";"os";"strings";"testing";"github.com/cycloidio/terracost/google";"google.golang.org/api/option")
func TestTrialG4MachineTypesAreSkipped(t *testing.T){
 skus,e:=os.ReadFile("../testdata/google/api/skus.json");if e!=nil{t.Fatal(e)}
 mt,e:=os.ReadFile("../testdata/google/api/machine_types.json");if e!=nil{t.Fatal(e)};var m map[string]interface{};if e=json.Unmarshal(mt,&m);e!=nil{t.Fatal(e)}
 items:=m["items"].([]interface{});for _,name:=range []string{"g4-standard-48","g4-standard-384"}{items=append(items,map[string]interface{}{"id":"99999999","name":name,"guestCpus":48,"memoryMb":196608})};m["items"]=items;mt,e=json.Marshal(m);if e!=nil{t.Fatal(e)}
 server:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){if strings.Contains(r.URL.Path,"machineTypes"){w.Write(mt)}else{w.Write(skus)}}));defer server.Close()
 ing,e:=google.NewIngester(context.Background(),nil,google.ComputeEngine.String(),"proj","europe-west1-b",google.WithGCPOption(option.WithEndpoint(server.URL),option.WithoutAuthentication()));if e!=nil{t.Fatal(e)}
 total,machines,g4:=0,0,0;for p:=range ing.Ingest(context.Background(),10){total++;if p.Product.Attributes["machine_type"]!=""{machines++};if strings.HasPrefix(p.Product.Attributes["machine_type"],"g4-"){g4++}}
 if e=ing.Err();e!=nil{t.Fatal(e)};if machines==0||g4!=0{t.Fatalf("machines=%d g4=%d",machines,g4)};t.Logf("Synthetic local API appended 2 G4 machine types: emitted total=%d supported machines=%d G4=%d",total,machines,g4)
}
